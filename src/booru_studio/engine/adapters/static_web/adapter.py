from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from booru_studio.common.errors import ErrorCode, ErrorConfidence, ErrorInstance
from booru_studio.engine.contracts import CandidateArtifact, HandoffSafety, NormalizedItemDescriptor, TransferDescriptor
from booru_studio.engine.network_scope import NetworkScopeBlocked, NetworkScopePolicy, NetworkScopePolicyMode, normalized_origin

_MAX_HTML_BYTES = 4 * 1024 * 1024
_MAX_REDIRECTS = 5
_MAX_CANDIDATES = 2_000
_MAX_TEXT = 1024
_MEDIA_EXT = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".jxl",
    ".mp4", ".webm", ".mkv", ".mov", ".m4v", ".mp3", ".m4a", ".aac",
    ".ogg", ".opus", ".flac", ".wav", ".m3u8", ".mpd",
}
_MEDIA_MIME_PREFIXES = ("image/", "video/", "audio/")
_META_MEDIA = {
    "og:image", "og:image:url", "og:video", "og:video:url", "og:audio", "og:audio:url",
    "twitter:image", "twitter:player:stream",
}


class StaticWebEngineError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str, *, confidence: ErrorConfidence = ErrorConfidence.STRONG) -> None:
        super().__init__(message)
        self.error = ErrorInstance(
            code=code,
            confidence=confidence,
            user_message_key=f"error.{code.value.lower()}",
            retryable=code in {ErrorCode.NETWORK_TIMEOUT, ErrorCode.NETWORK_RESET},
        )


@dataclass(frozen=True, slots=True)
class _RawCandidate:
    url: str
    title: str
    content_type: str | None = None


class _MediaHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[_RawCandidate] = []
        self.page_title = ""
        self._inside_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        values = {str(key).casefold(): str(value or "") for key, value in attrs}
        tag = tag.casefold()
        if tag == "title":
            self._inside_title = True
            return
        if tag in {"img", "video", "audio", "source"}:
            src = values.get("src") or values.get("data-src") or values.get("data-original")
            if src:
                self.candidates.append(_RawCandidate(src, values.get("alt") or values.get("title") or "", values.get("type") or None))
            if tag == "img":
                srcset = values.get("srcset") or values.get("data-srcset") or ""
                for entry in srcset.split(","):
                    candidate = entry.strip().split(" ", 1)[0]
                    if candidate:
                        self.candidates.append(_RawCandidate(candidate, values.get("alt") or values.get("title") or ""))
            if tag == "video" and values.get("poster"):
                self.candidates.append(_RawCandidate(values["poster"], values.get("title") or "poster", "image/*"))
            return
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").casefold()
            if key in _META_MEDIA and values.get("content"):
                self.candidates.append(_RawCandidate(values["content"], key))
            return
        if tag == "link":
            rel = {part.casefold() for part in values.get("rel", "").split()}
            as_kind = values.get("as", "").casefold()
            if values.get("href") and ("preload" in rel or "prefetch" in rel) and as_kind in {"image", "video", "audio"}:
                self.candidates.append(_RawCandidate(values["href"], values.get("title") or as_kind, f"{as_kind}/*"))

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self._inside_title = False
            self.page_title = " ".join(self._title_parts).strip()[:_MAX_TEXT]

    def handle_data(self, data: str) -> None:
        if self._inside_title and data.strip():
            self._title_parts.append(data.strip())


@dataclass(frozen=True, slots=True)
class StaticWebResult:
    final_page_url: str
    page_title: str
    items: tuple[NormalizedItemDescriptor, ...]
    blocked_candidate_count: int


class StaticWebAdapter:
    adapter_id = "static-web-v10"

    def __init__(self, *, session: requests.Session | None = None, resolver=None, allow_private_root: bool = False) -> None:  # type: ignore[no-untyped-def]
        self._session = session or requests.Session()
        self._session.trust_env = False
        self._resolver = resolver
        self._allow_private_root = allow_private_root
        self._session.headers.update({"User-Agent": "BooruStudio/10.0 StaticWeb", "Accept": "text/html,application/xhtml+xml"})

    def close(self) -> None:
        self._session.close()

    def _fetch(self, raw_input: str, *, timeout_s: float) -> tuple[str, bytes, Mapping[str, str], NetworkScopePolicy]:
        try:
            policy = NetworkScopePolicy(
                raw_input, user_supplied_root=True, allow_private_root=self._allow_private_root, resolver=self._resolver,
            )
        except NetworkScopeBlocked as exc:
            raise StaticWebEngineError(ErrorCode.NETWORK_SCOPE_BLOCKED, "static web root was rejected by network policy") from exc
        current = raw_input
        for _ in range(_MAX_REDIRECTS + 1):
            try:
                policy.authorize(current)
            except NetworkScopeBlocked as exc:
                raise StaticWebEngineError(ErrorCode.NETWORK_SCOPE_BLOCKED, "static web navigation was blocked") from exc
            for attempt in range(3):
                try:
                    response = self._session.get(current, allow_redirects=False, stream=True, timeout=timeout_s)
                    with response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location:
                                raise StaticWebEngineError(ErrorCode.ENGINE_PROTOCOL_ERROR, "redirect response lacked Location")
                            current = urljoin(current, location)
                            break
                        if response.status_code == 429:
                            raise StaticWebEngineError(ErrorCode.RATE_LIMITED, "static web request was rate limited")
                        if response.status_code in {401, 403}:
                            raise StaticWebEngineError(ErrorCode.AUTH_REQUIRED, "static web source requires authentication")
                        if response.status_code == 404:
                            raise StaticWebEngineError(ErrorCode.SOURCE_NOT_FOUND, "static web source was not found")
                        if not 200 <= response.status_code < 300:
                            raise StaticWebEngineError(ErrorCode.ENGINE_UNKNOWN_ERROR, f"static web HTTP {response.status_code}")
                        content_type = str(response.headers.get("Content-Type") or "").casefold()
                        if "html" not in content_type and "xhtml" not in content_type:
                            raise StaticWebEngineError(ErrorCode.UNSUPPORTED_MEDIA, "static resolver expected an HTML document")
                        chunks: list[bytes] = []
                        size = 0
                        for chunk in response.iter_content(64 * 1024):
                            if not chunk:
                                continue
                            size += len(chunk)
                            if size > _MAX_HTML_BYTES:
                                raise StaticWebEngineError(ErrorCode.RESOURCE_EXHAUSTED, "HTML document exceeded 4 MiB resolver ceiling")
                            chunks.append(chunk)
                        return current, b"".join(chunks), MappingProxyType(dict(response.headers)), policy
                except requests.Timeout as exc:
                    if attempt == 2:
                        raise StaticWebEngineError(ErrorCode.NETWORK_TIMEOUT, "static web request timed out") from exc
                except requests.RequestException as exc:
                    if attempt == 2:
                        raise StaticWebEngineError(ErrorCode.NETWORK_RESET, "static web request failed") from exc
        raise StaticWebEngineError(ErrorCode.ENGINE_PROTOCOL_ERROR, "static web redirect ceiling exceeded")

    def discover(self, raw_input: str, *, timeout_s: float = 15.0) -> StaticWebResult:
        final_url, body, headers, policy = self._fetch(raw_input, timeout_s=timeout_s)
        encoding = requests.utils.get_encoding_from_headers(headers) or "utf-8"
        try:
            text = body.decode(encoding, errors="replace")
        except LookupError:
            text = body.decode("utf-8", errors="replace")
        parser = _MediaHtmlParser()
        parser.feed(text)
        items: list[NormalizedItemDescriptor] = []
        blocked = 0
        seen: set[str] = set()
        explicit_private_root = policy.allow_private_root
        root_origin = policy.root_origin
        for raw in parser.candidates[:_MAX_CANDIDATES]:
            absolute = urljoin(final_url, html.unescape(raw.url).strip())
            if absolute in seen:
                continue
            seen.add(absolute)
            try:
                decision = policy.authorize(absolute)
            except NetworkScopeBlocked:
                blocked += 1
                continue
            if not self._looks_like_media(absolute, raw.content_type):
                continue
            index = len(items)
            filename = self._filename(absolute, index)
            mode = NetworkScopePolicyMode.PUBLIC_ONLY
            scope_root: str | None = None
            if explicit_private_root and decision.origin == root_origin:
                mode = NetworkScopePolicyMode.ROOT_OR_PUBLIC
                scope_root = final_url
            descriptor = TransferDescriptor(
                url=absolute,
                referer=final_url,
                content_type=raw.content_type,
                origin_scope="USER_EXPLICIT_PRIVATE" if scope_root else "PUBLIC_WEB",
                redirect_policy="HTTP_OR_HTTPS",
                network_scope_policy=mode.value,
                network_scope_root=scope_root,
                handoff_safety=HandoffSafety.CONDITIONAL,
            )
            safe_source = self._redacted(absolute)
            identity = "web:" + hashlib.sha256(safe_source.encode("utf-8")).hexdigest()[:32]
            title = (raw.title or PurePosixPath(urlsplit(absolute).path).name or f"Media {index + 1}")[:_MAX_TEXT]
            items.append(NormalizedItemDescriptor(
                source_identity=identity,
                media_kind=self._media_kind(absolute, raw.content_type),
                display_title=title,
                source_index=index,
                discovery_sequence=index,
                candidate_artifacts=(CandidateArtifact("PRIMARY", filename, descriptor, content_type=raw.content_type),),
                sanitized_metadata={"resolver": self.adapter_id, "source_url": safe_source},
            ))
        return StaticWebResult(final_url, parser.page_title, tuple(items), blocked)

    @staticmethod
    def _redacted(url: str) -> str:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", ""))

    @staticmethod
    def _looks_like_media(url: str, content_type: str | None) -> bool:
        if content_type and content_type.casefold().startswith(_MEDIA_MIME_PREFIXES):
            return True
        suffix = PurePosixPath(urlsplit(url).path).suffix.casefold()
        return suffix in _MEDIA_EXT

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
        return (name or f"media-{index + 1}.bin")[:240]
