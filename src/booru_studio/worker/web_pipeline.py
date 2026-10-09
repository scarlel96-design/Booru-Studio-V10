from __future__ import annotations

import hashlib
import threading
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass
from enum import StrEnum

from booru_studio.engine.adapters.playwright_browser import BrowserAssistAdapter, BrowserAssistResult
from booru_studio.engine.adapters.static_web import StaticWebAdapter, StaticWebResult
from booru_studio.domain.presentation import MediaPresentationContract
from booru_studio.engine.contracts import NormalizedItemDescriptor


class WebResolutionMode(StrEnum):
    STATIC = "STATIC"
    BROWSER = "BROWSER"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class WebResolutionResult:
    mode: WebResolutionMode
    final_page_url: str
    page_title: str
    items: tuple[NormalizedItemDescriptor, ...]
    blocked_count: int = 0

    @property
    def presentation(self) -> MediaPresentationContract | None:
        if len(self.items) == 1:
            return MediaPresentationContract.single_media()
        if len(self.items) > 1:
            return MediaPresentationContract.web_page()
        return None

    @property
    def collection_identity(self) -> str | None:
        if len(self.items) <= 1:
            return None
        try:
            parts = urlsplit(self.final_page_url)
            host = parts.hostname or ""
            if parts.port:
                host = f"{host}:{parts.port}"
            redacted = urlunsplit((parts.scheme, host, parts.path, "", ""))
        except ValueError:
            redacted = "invalid://redacted"
        digest = hashlib.sha256(redacted.encode("utf-8")).hexdigest()[:32]
        return f"webpage:{digest}"


class WebResolverPipeline:
    """Worker-owned Static -> Browser fallback pipeline.

    Browser Assist is invoked only when deterministic static HTML discovery returns no usable media.
    Browser observations are still normalized into ordinary descriptors; the browser never becomes a
    durable downloader or FileCommit owner.
    """

    def __init__(
        self,
        *,
        static: StaticWebAdapter | None = None,
        browser: BrowserAssistAdapter | None = None,
        allow_private_root: bool = False,
    ) -> None:
        self._static = static or StaticWebAdapter(allow_private_root=allow_private_root)
        self._browser = browser or BrowserAssistAdapter(allow_private_root=allow_private_root)

    def resolve(
        self,
        raw_input: str,
        *,
        cancel_event: threading.Event,
        allow_browser_fallback: bool = True,
    ) -> WebResolutionResult:
        if cancel_event.is_set():
            raise RuntimeError("web resolution cancelled")
        static_result: StaticWebResult = self._static.discover(raw_input)
        if static_result.items:
            return WebResolutionResult(
                WebResolutionMode.STATIC,
                static_result.final_page_url,
                static_result.page_title,
                static_result.items,
                static_result.blocked_candidate_count,
            )
        if not allow_browser_fallback:
            return WebResolutionResult(WebResolutionMode.NONE, static_result.final_page_url, static_result.page_title, ())
        browser_result: BrowserAssistResult = self._browser.discover(
            raw_input, cancel_event=cancel_event,
        )
        return WebResolutionResult(
            WebResolutionMode.BROWSER if browser_result.items else WebResolutionMode.NONE,
            browser_result.final_page_url,
            browser_result.page_title,
            browser_result.items,
            browser_result.blocked_request_count + browser_result.blocked_candidate_count,
        )
