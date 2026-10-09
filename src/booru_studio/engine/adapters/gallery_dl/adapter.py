from __future__ import annotations

import hashlib
import re
from importlib.metadata import PackageNotFoundError, version
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from booru_studio.common.errors import ErrorCode, ErrorConfidence, ErrorInstance
from booru_studio.engine.contracts import (
    CandidateArtifact,
    DiscoveryResult,
    EngineCapabilities,
    HandoffSafety,
    NormalizedItemDescriptor,
    ProbeResult,
    ProbeSupport,
    TransferDescriptor,
)

# gallery-dl's extractor Message enum has used these protocol values for DataJob output.
# They are hidden behind GalleryDlBackend so a future upstream change is fixed in one place.
GALLERY_DL_PIN = "1.32.9"
_MESSAGE_URL = 3
_MESSAGE_QUEUE = 6
_MAX_ITEMS = 100_000
_MAX_QUEUE_RESOLVE_DEPTH = 8
_MAX_METADATA_TEXT = 512
_SECRET_HEADER_NAMES = {
    "authorization", "proxy-authorization", "cookie", "x-api-key", "x-auth-token",
}
_SAFE_HANDOFF_HEADERS = {
    "accept", "accept-language", "origin", "referer", "user-agent", "range",
}
_SENSITIVE_QUERY_NAMES = re.compile(
    r"(?:token|sig(?:nature)?|auth|key|policy|credential|expires?|session|jwt|secret)", re.I
)
_IMAGE_EXT = {"jpg", "jpeg", "png", "gif", "webp", "avif", "bmp", "jxl"}
_VIDEO_EXT = {"mp4", "webm", "mkv", "mov", "m4v", "avi"}
_AUDIO_EXT = {"mp3", "m4a", "aac", "ogg", "opus", "flac", "wav"}


class GalleryDlEngineError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str, *, confidence: ErrorConfidence = ErrorConfidence.STRONG) -> None:
        super().__init__(message)
        self.error = ErrorInstance(
            code=code,
            confidence=confidence,
            user_message_key=f"error.{code.value.lower()}",
            retryable=code in {ErrorCode.NETWORK_RESET, ErrorCode.NETWORK_TIMEOUT, ErrorCode.RATE_LIMITED},
        )


@dataclass(frozen=True, slots=True)
class GalleryDlRecord:
    message_type: int
    url: str
    metadata: dict[str, Any]


class GalleryDlBackend(Protocol):
    def collect(self, raw_input: str) -> Sequence[GalleryDlRecord]: ...


class GalleryDlPythonBackend:
    """Thin, lazy wrapper around gallery-dl's extractor/DataJob APIs.

    The import lives here rather than at module import time so Core/source QA does not gain a hard
    dependency on gallery-dl. Production Engine Packs install the exact pinned distribution.
    """

    @staticmethod
    def _verify_runtime() -> None:
        try:
            installed = version("gallery-dl")
        except PackageNotFoundError as exc:
            raise GalleryDlEngineError(ErrorCode.ENGINE_UNAVAILABLE, "gallery-dl is not installed") from exc
        if installed != GALLERY_DL_PIN:
            raise GalleryDlEngineError(
                ErrorCode.ENGINE_PROTOCOL_ERROR,
                f"gallery-dl version mismatch: expected {GALLERY_DL_PIN}, got {installed}",
                confidence=ErrorConfidence.EXACT,
            )

    def probe_extractor(self, raw_input: str) -> tuple[str, str] | None:
        self._verify_runtime()
        try:
            from gallery_dl import extractor  # type: ignore[import-not-found]
            found = extractor.find(raw_input)
        except Exception as exc:
            raise _map_gallery_exception(exc) from exc
        if found is None:
            return None
        return str(getattr(found, "category", "gallery")), str(getattr(found, "subcategory", "item"))

    def collect(self, raw_input: str) -> Sequence[GalleryDlRecord]:
        self._verify_runtime()
        try:
            from gallery_dl import config  # type: ignore[import-not-found]
            from gallery_dl.job import DataJob  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise GalleryDlEngineError(ErrorCode.ENGINE_UNAVAILABLE, "gallery-dl is not installed") from exc
        try:
            # DataJob defaults to sys.stdout and filters private ``_...`` metadata. Both defaults are
            # wrong for an embedded Worker: stdout may be an IPC transport, while _http_headers and
            # _http_validate are required to decide whether DirectHTTP handoff is safe.  A Job Worker
            # owns one gallery resolution phase, so this scoped gallery-dl config mutation cannot race
            # with another gallery job in the same process.
            with config.apply([(("output",), "private", True)]):
                job = DataJob(
                    url=raw_input,
                    file=None,
                    resolve=_MAX_QUEUE_RESOLVE_DEPTH,
                )
                job.run()
                data = list(job.data)
                job_exception = getattr(job, "exception", None)
        except GalleryDlEngineError:
            raise
        except Exception as exc:  # Upstream exception taxonomy is normalized at this boundary.
            raise _map_gallery_exception(exc) from exc

        # DataJob deliberately captures extractor exceptions and still returns 0. Treat its explicit
        # exception field as authoritative instead of misclassifying an error as successful discovery.
        if job_exception is not None:
            raise _map_gallery_exception(job_exception) from job_exception
        if len(data) > _MAX_ITEMS:
            raise GalleryDlEngineError(ErrorCode.RESOURCE_EXHAUSTED, "gallery-dl discovery exceeded item ceiling")
        records: list[GalleryDlRecord] = []
        for row in data:
            # DataJob may append a two-element (-1, error-dict) record for a captured error. A missing
            # ``job.exception`` on such a row is an upstream contract violation, never a valid item.
            if isinstance(row, (list, tuple)) and row and row[0] == -1:
                raise GalleryDlEngineError(
                    ErrorCode.ENGINE_PROTOCOL_ERROR,
                    "gallery-dl returned an error record without an exception",
                    confidence=ErrorConfidence.STRONG,
                )
            if not isinstance(row, (list, tuple)) or len(row) < 3:
                continue
            message_type, url, metadata = row[0], row[1], row[2]
            if not isinstance(message_type, int) or not isinstance(url, str) or not isinstance(metadata, dict):
                continue
            records.append(GalleryDlRecord(message_type, url, dict(metadata)))
        return tuple(records)


def _map_gallery_exception(exc: BaseException) -> GalleryDlEngineError:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "auth" in name or "login" in text or "authentication" in text:
        code = ErrorCode.AUTH_REQUIRED
    elif "notfound" in name or "not found" in text or "404" in text:
        code = ErrorCode.SOURCE_NOT_FOUND
    elif "429" in text or "ratelimit" in name or "rate limit" in text:
        code = ErrorCode.RATE_LIMITED
    elif "timeout" in name or "timed out" in text:
        code = ErrorCode.NETWORK_TIMEOUT
    elif "connection" in name or "connection" in text:
        code = ErrorCode.NETWORK_RESET
    elif "unsupported" in name or "unsupported" in text:
        code = ErrorCode.UNSUPPORTED_MEDIA
    else:
        code = ErrorCode.ENGINE_UNKNOWN_ERROR
    return GalleryDlEngineError(
        code, f"gallery-dl failed: {type(exc).__name__}", confidence=ErrorConfidence.HEURISTIC
    )


def _redacted_url(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return "invalid://redacted"
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit((parts.scheme, host + port, parts.path, "", ""))


def _source_identity(url: str, metadata: dict[str, Any]) -> str:
    category = str(metadata.get("category") or "gallery")[:64]
    subcategory = str(metadata.get("subcategory") or "item")[:64]
    raw_id = metadata.get("id") or metadata.get("post_id") or metadata.get("md5") or metadata.get("hash")
    if raw_id is not None and str(raw_id):
        suffix = re.sub(r"[^A-Za-z0-9._:-]+", "_", str(raw_id))[:160]
    else:
        suffix = hashlib.sha256(_redacted_url(url).encode("utf-8")).hexdigest()[:32]
    return f"gallery:{category}:{subcategory}:{suffix}"


def _text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    value = str(value).replace("\x00", " ").strip()
    return value[:_MAX_METADATA_TEXT]


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _filename(url: str, metadata: dict[str, Any], sequence: int) -> str:
    name = _text(metadata.get("filename"))
    ext = _text(metadata.get("extension")).lstrip(".").lower()
    if not name:
        try:
            name = PurePath(urlsplit(url).path).name
        except ValueError:
            name = ""
        if name and "." in name and not ext:
            ext = name.rsplit(".", 1)[1].lower()
        elif name and ext and not name.lower().endswith("." + ext):
            name = f"{name}.{ext}"
    elif ext and not name.lower().endswith("." + ext):
        name = f"{name}.{ext}"
    if not name:
        name = f"gallery_{sequence:06d}" + (f".{ext}" if ext else ".bin")
    # One file only; never let extractor metadata become a path traversal.
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", Path(name).name).strip(" .")
    return (name or f"gallery_{sequence:06d}.bin")[:240]


def _media_kind(filename: str, metadata: dict[str, Any]) -> str:
    ext = _text(metadata.get("extension")).lower().lstrip(".")
    if not ext and "." in filename:
        ext = filename.rsplit(".", 1)[1].lower()
    if ext in _IMAGE_EXT:
        return "IMAGE"
    if ext in _VIDEO_EXT:
        return "VIDEO"
    if ext in _AUDIO_EXT:
        return "AUDIO"
    return "FILE"


def _descriptor(url: str, metadata: dict[str, Any]) -> TransferDescriptor:
    if url.startswith("ytdl:"):
        return TransferDescriptor(url=url, handoff_safety=HandoffSafety.UNSAFE)
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return TransferDescriptor(url=url, handoff_safety=HandoffSafety.UNSAFE)

    raw_headers = metadata.get("_http_headers") or {}
    if not isinstance(raw_headers, dict):
        raw_headers = {}
    headers = {str(k): str(v) for k, v in raw_headers.items() if v is not None}
    lower = {k.lower(): v for k, v in headers.items()}
    requires_secret_header = bool(_SECRET_HEADER_NAMES & lower.keys())
    requires_custom_validator = metadata.get("_http_validate") is not None
    unknown_headers = {key for key in lower if key not in _SAFE_HANDOFF_HEADERS and key not in _SECRET_HEADER_NAMES}
    sensitive_query = any(_SENSITIVE_QUERY_NAMES.search(key) for key, _ in parse_qsl(parts.query, keep_blank_values=True))

    if requires_secret_header or requires_custom_validator:
        safety = HandoffSafety.UNSAFE
    elif headers or sensitive_query or unknown_headers:
        safety = HandoffSafety.CONDITIONAL
    else:
        safety = HandoffSafety.SAFE

    expected_size = (
        _positive_int(metadata.get("filesize"))
        or _positive_int(metadata.get("file_size"))
        or _positive_int(metadata.get("size"))
    )
    referer = lower.get("referer")
    return TransferDescriptor(
        url=url,
        headers=headers,
        referer=referer,
        expected_size=expected_size,
        content_type=_text(metadata.get("content_type")) or None,
        origin_scope=f"{parts.scheme}://{parts.hostname}",
        redirect_policy="HTTPS_ONLY" if parts.scheme == "https" else "HTTP_OR_HTTPS",
        resume_semantics="VALIDATOR_REQUIRED",
        handoff_safety=safety,
    )


def _sanitized_metadata(metadata: dict[str, Any]) -> dict[str, object]:
    # Durable/diagnostic-safe allow-list. Do not copy arbitrary extractor state (cookies, headers,
    # tokens, signed URLs, PathfmtProxy, response validators, etc.).
    allowed = (
        "category", "subcategory", "id", "post_id", "md5", "extension", "width", "height",
        "rating", "uploader", "username", "date", "num",
    )
    result: dict[str, object] = {}
    for key in allowed:
        value = metadata.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            if isinstance(value, str):
                value = _text(value)
            result[key] = value
    return result


class GalleryDlAdapter:
    adapter_id = "gallery-dl"

    def __init__(self, backend: GalleryDlBackend | None = None) -> None:
        self._backend = backend or GalleryDlPythonBackend()

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities()

    def probe(self, raw_input: str) -> ProbeResult:
        try:
            parts = urlsplit(raw_input)
        except ValueError:
            return ProbeResult(ProbeSupport.NO, 1.0, reason="invalid URL")
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return ProbeResult(ProbeSupport.NO, 1.0, reason="gallery-dl requires an HTTP(S) source")
        probe_method = getattr(self._backend, "probe_extractor", None)
        if callable(probe_method):
            found = probe_method(raw_input)
            if found is None:
                return ProbeResult(ProbeSupport.NO, 0.99, specificity=90, reason="no gallery-dl extractor matched")
            category, subcategory = found
            return ProbeResult(
                ProbeSupport.YES, 0.99, specificity=95, cost_class="LOW",
                requires_network_probe=False, reason=f"gallery-dl:{category}:{subcategory}",
            )
        # Injected/test backends may not expose extractor matching. Do not perform discovery merely to probe.
        return ProbeResult(
            ProbeSupport.MAYBE, 0.55, specificity=10, cost_class="LOW",
            requires_network_probe=False, reason="backend extractor matcher unavailable",
        )

    def resolve(self, raw_input: str):
        # Compatibility with the original Sprint-0 ResolverAdapter contract.
        from booru_studio.engine.contracts import ResolutionResult
        probe = self.probe(raw_input)
        if probe.support is ProbeSupport.NO:
            raise GalleryDlEngineError(ErrorCode.UNSUPPORTED_MEDIA, probe.reason)
        return ResolutionResult(source_kind="BOORU_GALLERY", display_title=_redacted_url(raw_input))

    def discover(self, raw_input: str) -> DiscoveryResult:
        records = self._backend.collect(raw_input)
        items: list[NormalizedItemDescriptor] = []
        queued: list[str] = []
        sequence = 0
        for record in records:
            if record.message_type == _MESSAGE_QUEUE:
                # Child URLs can themselves contain secrets. Keep them runtime-only and never copy them
                # into the durable normalized item metadata.
                if record.url.startswith(("http://", "https://")):
                    queued.append(record.url)
                continue
            if record.message_type != _MESSAGE_URL:
                continue
            sequence += 1
            filename = _filename(record.url, record.metadata, sequence)
            transfer = _descriptor(record.url, record.metadata)
            source_index = _positive_int(record.metadata.get("num"))
            if source_index is None:
                source_index = sequence - 1
            display = (
                _text(record.metadata.get("title"))
                or _text(record.metadata.get("name"))
                or filename
            )
            item = NormalizedItemDescriptor(
                source_identity=_source_identity(record.url, record.metadata),
                media_kind=_media_kind(filename, record.metadata),
                display_title=display,
                source_index=source_index,
                discovery_sequence=sequence - 1,
                width=_positive_int(record.metadata.get("width")),
                height=_positive_int(record.metadata.get("height")),
                candidate_artifacts=(CandidateArtifact(
                    role="PRIMARY",
                    suggested_filename=filename,
                    descriptor=transfer,
                    expected_size=transfer.expected_size,
                    content_type=transfer.content_type,
                ),),
                sanitized_metadata=_sanitized_metadata(record.metadata),
            )
            items.append(item)
            if len(items) > _MAX_ITEMS:
                raise GalleryDlEngineError(ErrorCode.RESOURCE_EXHAUSTED, "gallery discovery item ceiling exceeded")
        return DiscoveryResult(source_kind="BOORU_GALLERY", items=items, queued_inputs=queued)


class GalleryDirectHandoffPlanner:
    """Creates an ephemeral DirectHTTP wire entry from an already claimed Artifact.

    The resulting dict may contain signed URLs/headers and MUST NOT be persisted. It is intended only
    for the Core->Worker START_RUN execution-plan payload or in-Worker execution graph.
    """

    @staticmethod
    def build(candidate: CandidateArtifact, *, artifact_id: str, generation: int, staging_path: Path) -> dict[str, object]:
        descriptor = candidate.descriptor
        if descriptor.handoff_safety is HandoffSafety.UNSAFE:
            raise ValueError("UNSAFE gallery descriptor cannot be handed to DirectHTTP")
        headers = dict(descriptor.headers)
        if descriptor.referer and not any(k.lower() == "referer" for k in headers):
            headers["Referer"] = descriptor.referer
        fingerprint = hashlib.sha256(descriptor.url.encode("utf-8")).hexdigest()
        return {
            "artifact_id": artifact_id,
            "generation": generation,
            "url": descriptor.url,
            "headers": headers,
            "staging_path": str(staging_path),
            "sidecar_path": str(staging_path.with_suffix(staging_path.suffix + ".resume.json")),
            "source_fingerprint": fingerprint,
            "expected_size": descriptor.expected_size,
            "expected_sha256": None,
            "redirect_policy": descriptor.redirect_policy,
            "timeout_s": 30.0,
            "retry_ceiling": 2,
        }
