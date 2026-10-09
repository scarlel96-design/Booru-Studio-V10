from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import PurePosixPath
from typing import Protocol, Sequence
from urllib.parse import urljoin, urlsplit, urlunsplit

from booru_studio.common.errors import ErrorCode, ErrorConfidence, ErrorInstance
from booru_studio.engine.contracts import CandidateArtifact, HandoffSafety, NormalizedItemDescriptor, TransferDescriptor
from booru_studio.engine.network_scope import NetworkScopeBlocked, NetworkScopePolicy, NetworkScopePolicyMode

PLAYWRIGHT_PIN = "1.62.0"
_MAX_REQUESTS = 2_000
_MAX_CANDIDATES = 2_000
_MEDIA_PREFIX = ("image/", "video/", "audio/")
_MEDIA_EXT = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".jxl",
    ".mp4", ".webm", ".mkv", ".mov", ".m4v", ".mp3", ".m4a", ".aac",
    ".ogg", ".opus", ".flac", ".wav", ".m3u8", ".mpd",
}


class BrowserAssistEngineError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str, *, confidence: ErrorConfidence = ErrorConfidence.STRONG) -> None:
        super().__init__(message)
        self.error = ErrorInstance(
            code=code,
            confidence=confidence,
            user_message_key=f"error.{code.value.lower()}",
            retryable=code in {ErrorCode.NETWORK_TIMEOUT, ErrorCode.NETWORK_RESET, ErrorCode.BROWSER_CRASHED},
        )


@dataclass(frozen=True, slots=True)
class BrowserObservation:
    url: str
    content_type: str | None = None
    title: str = ""


@dataclass(frozen=True, slots=True)
class BrowserBackendResult:
    final_page_url: str
    page_title: str
    observations: tuple[BrowserObservation, ...]
    blocked_request_count: int = 0


class BrowserObservationBackend(Protocol):
    def observe(
        self,
        raw_input: str,
        *,
        policy: NetworkScopePolicy,
        cancel_event: threading.Event,
        timeout_s: float,
    ) -> BrowserBackendResult: ...


class PlaywrightPythonBackend:
    """Installed-Edge browser observer. It never accepts browser-owned downloads.

    The context is non-persistent, service workers are blocked so route interception remains
    authoritative for ordinary page traffic, and every routed request is checked against the
    derived-network policy before it can leave the browser context.
    """

    def __init__(self, *, channel: str = "msedge") -> None:
        self.channel = channel

    @staticmethod
    def _verify_runtime() -> None:
        try:
            installed = version("playwright")
        except PackageNotFoundError as exc:
            raise BrowserAssistEngineError(ErrorCode.BROWSER_UNAVAILABLE, "Playwright is not installed") from exc
        if installed != PLAYWRIGHT_PIN:
            raise BrowserAssistEngineError(
                ErrorCode.BROWSER_PROTOCOL_ERROR,
                f"Playwright version mismatch: expected {PLAYWRIGHT_PIN}, got {installed}",
                confidence=ErrorConfidence.EXACT,
            )

    def observe(
        self,
        raw_input: str,
        *,
        policy: NetworkScopePolicy,
        cancel_event: threading.Event,
        timeout_s: float,
    ) -> BrowserBackendResult:
        self._verify_runtime()
        try:
            from playwright.sync_api import Error as PlaywrightError  # type: ignore[import-not-found]
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # type: ignore[import-not-found]
            from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise BrowserAssistEngineError(ErrorCode.BROWSER_UNAVAILABLE, "Playwright import failed") from exc

        observations: list[BrowserObservation] = []
        blocked = 0
        request_count = 0
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(channel=self.channel, headless=True, chromium_sandbox=True)
                except PlaywrightError as exc:
                    raise BrowserAssistEngineError(ErrorCode.BROWSER_UNAVAILABLE, "Microsoft Edge could not be launched") from exc
                try:
                    context = browser.new_context(
                        accept_downloads=False,
                        service_workers="block",
                        bypass_csp=False,
                    )

                    def route_handler(route) -> None:  # type: ignore[no-untyped-def]
                        nonlocal blocked, request_count
                        request_count += 1
                        request = route.request
                        request_url = str(request.url)
                        if cancel_event.is_set() or request_count > _MAX_REQUESTS:
                            blocked += 1
                            route.abort("blockedbyclient")
                            return
                        try:
                            policy.authorize(request_url)
                        except NetworkScopeBlocked:
                            blocked += 1
                            route.abort("blockedbyclient")
                            return
                        # Browser Assist is an observer, not a second downloader. Common image/media
                        # resource requests are captured before transfer and aborted; V10 DirectHTTP
                        # owns the real byte transfer after candidate normalization.
                        suffix = PurePosixPath(urlsplit(request_url).path).suffix.casefold()
                        resource_type = str(request.resource_type).casefold()
                        if resource_type in {"image", "media"} or suffix in _MEDIA_EXT:
                            hint = "image/*" if resource_type == "image" else None
                            observations.append(BrowserObservation(request_url, hint, f"browser-{resource_type}"))
                            route.abort("blockedbyclient")
                            return
                        route.continue_()

                    def on_response(response) -> None:  # type: ignore[no-untyped-def]
                        value = str(response.headers.get("content-type") or "").split(";", 1)[0].strip().casefold()
                        if value.startswith(_MEDIA_PREFIX):
                            observations.append(BrowserObservation(str(response.url), value))

                    context.route("**/*", route_handler)
                    # Browser Assist does not need bidirectional application sockets to discover
                    # ordinary media candidates. Block them by default so WebSocket traffic cannot
                    # become an ungoverned SSRF/resource channel.
                    context.route_web_socket("**/*", lambda ws: ws.close(code=1000, reason="Booru Studio Browser Assist"))
                    context.on("response", on_response)
                    page = context.new_page()
                    page.on("popup", lambda popup: popup.close())
                    page.goto(raw_input, wait_until="domcontentloaded", timeout=max(1, int(timeout_s * 1000)))
                    if cancel_event.is_set():
                        raise BrowserAssistEngineError(ErrorCode.BROWSER_CRASHED, "browser observation cancelled")
                    page.wait_for_timeout(min(1_500, max(0, int(timeout_s * 100))))
                    # DOM URLs supplement the network observer for lazy/deferred media. They are
                    # revalidated by BrowserAssistAdapter before DirectHTTP handoff.
                    dom_rows = page.eval_on_selector_all(
                        "img,video,audio,source,meta[property^='og:'],meta[name='twitter:image']",
                        """els => els.map(e => ({
                            url: e.currentSrc || e.src || e.content || '',
                            title: e.alt || e.title || e.getAttribute('property') || e.getAttribute('name') || '',
                            type: e.type || '',
                            tag: (e.tagName || '').toLowerCase()
                        })).filter(x => x.url)""",
                    )
                    if isinstance(dom_rows, list):
                        for row in dom_rows[:_MAX_CANDIDATES]:
                            if isinstance(row, dict) and isinstance(row.get("url"), str):
                                raw_type = str(row.get("type") or "")
                                tag = str(row.get("tag") or "").casefold()
                                if not raw_type:
                                    if tag == "img":
                                        raw_type = "image/*"
                                    elif tag == "audio":
                                        raw_type = "audio/*"
                                    elif tag in {"video", "source"}:
                                        raw_type = "video/*"
                                observations.append(BrowserObservation(
                                    row["url"], raw_type or None, str(row.get("title") or "")[:1024],
                                ))
                    final_url = page.url
                    title = page.title()[:1024]
                    context.close()
                    return BrowserBackendResult(final_url, title, tuple(observations[:_MAX_CANDIDATES]), blocked)
                finally:
                    browser.close()
        except BrowserAssistEngineError:
            raise
        except PlaywrightTimeoutError as exc:
            raise BrowserAssistEngineError(ErrorCode.NETWORK_TIMEOUT, "browser navigation timed out") from exc
        except PlaywrightError as exc:
            raise BrowserAssistEngineError(ErrorCode.BROWSER_CRASHED, "browser observation failed") from exc


@dataclass(frozen=True, slots=True)
class BrowserAssistResult:
    final_page_url: str
    page_title: str
    items: tuple[NormalizedItemDescriptor, ...]
    blocked_request_count: int
    blocked_candidate_count: int


class BrowserAssistAdapter:
    adapter_id = "playwright-browser-assist-v10"

    def __init__(
        self, backend: BrowserObservationBackend | None = None, *, resolver=None, allow_private_root: bool = False
    ) -> None:  # type: ignore[no-untyped-def]
        self._backend = backend or PlaywrightPythonBackend()
        self._resolver = resolver
        self._allow_private_root = allow_private_root

    def discover(
        self,
        raw_input: str,
        *,
        cancel_event: threading.Event,
        timeout_s: float = 20.0,
    ) -> BrowserAssistResult:
        try:
            policy = NetworkScopePolicy(
                raw_input, user_supplied_root=True, allow_private_root=self._allow_private_root, resolver=self._resolver,
            )
            policy.authorize(raw_input)
        except NetworkScopeBlocked as exc:
            raise BrowserAssistEngineError(ErrorCode.NETWORK_SCOPE_BLOCKED, "browser root was rejected by network policy") from exc
        result = self._backend.observe(raw_input, policy=policy, cancel_event=cancel_event, timeout_s=timeout_s)
        try:
            policy.authorize(result.final_page_url)
        except NetworkScopeBlocked as exc:
            raise BrowserAssistEngineError(ErrorCode.NETWORK_SCOPE_BLOCKED, "browser escaped its permitted network scope") from exc
        items: list[NormalizedItemDescriptor] = []
        blocked_candidates = 0
        seen: set[str] = set()
        for row in result.observations[:_MAX_CANDIDATES]:
            absolute = urljoin(result.final_page_url, row.url)
            if absolute in seen:
                continue
            seen.add(absolute)
            try:
                decision = policy.authorize(absolute)
            except NetworkScopeBlocked:
                blocked_candidates += 1
                continue
            if not self._looks_like_media(absolute, row.content_type):
                continue
            mode = NetworkScopePolicyMode.PUBLIC_ONLY
            scope_root: str | None = None
            if policy.allow_private_root and decision.origin == policy.root_origin:
                mode = NetworkScopePolicyMode.ROOT_OR_PUBLIC
                scope_root = result.final_page_url
            descriptor = TransferDescriptor(
                url=absolute,
                referer=result.final_page_url,
                content_type=row.content_type,
                origin_scope="USER_EXPLICIT_PRIVATE" if scope_root else "PUBLIC_WEB",
                redirect_policy="HTTP_OR_HTTPS",
                network_scope_policy=mode.value,
                network_scope_root=scope_root,
                handoff_safety=HandoffSafety.CONDITIONAL,
            )
            redacted = self._redacted(absolute)
            identity = "browser:" + hashlib.sha256(redacted.encode("utf-8")).hexdigest()[:32]
            index = len(items)
            name = self._filename(absolute, index)
            items.append(NormalizedItemDescriptor(
                source_identity=identity,
                media_kind=self._media_kind(absolute, row.content_type),
                display_title=(row.title or name)[:1024],
                source_index=index,
                discovery_sequence=index,
                candidate_artifacts=(CandidateArtifact("PRIMARY", name, descriptor, content_type=row.content_type),),
                sanitized_metadata={"resolver": self.adapter_id, "source_url": redacted},
            ))
        return BrowserAssistResult(
            result.final_page_url,
            result.page_title,
            tuple(items),
            result.blocked_request_count,
            blocked_candidates,
        )

    @staticmethod
    def _redacted(url: str) -> str:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", ""))

    @staticmethod
    def _looks_like_media(url: str, content_type: str | None) -> bool:
        value = (content_type or "").casefold()
        if value.startswith(_MEDIA_PREFIX):
            return True
        return PurePosixPath(urlsplit(url).path).suffix.casefold() in _MEDIA_EXT

    @staticmethod
    def _media_kind(url: str, content_type: str | None) -> str:
        value = (content_type or "").casefold()
        if value.startswith("image/"):
            return "IMAGE"
        if value.startswith("audio/"):
            return "AUDIO"
        if value.startswith("video/"):
            return "VIDEO"
        suffix = PurePosixPath(urlsplit(url).path).suffix.casefold()
        if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".jxl"}:
            return "IMAGE"
        if suffix in {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav"}:
            return "AUDIO"
        return "VIDEO"

    @staticmethod
    def _filename(url: str, index: int) -> str:
        name = PurePosixPath(urlsplit(url).path).name
        name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", name).strip(" .")
        return (name or f"browser-media-{index + 1}.bin")[:240]
