from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePath
from types import MappingProxyType
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from booru_studio.common.errors import ErrorCode, ErrorConfidence, ErrorInstance
from booru_studio.domain.presentation import MediaPresentationContract
from booru_studio.engine.contracts import (
    CandidateArtifact,
    CapabilityLevel,
    EngineCapabilities,
    ExecutionCapabilityProfile,
    HandoffSafety,
    ManagedMediaExecutionPolicy,
    ManagedNetworkControlLevel,
    NormalizedItemDescriptor,
    PauseSemantics,
    ProbeResult,
    ProbeSupport,
    ResumeControl,
    TransferDescriptor,
)

# Sprint 7 pins the latest stable release observed on the official GitHub release channel on
# 2026-08-23.  The Engine Pack owns this dependency and verifies it at runtime before use.
YT_DLP_PIN = "2026.08.19"
YT_DLP_EJS_PIN = "0.8.0"
DENO_MIN_VERSION = (2, 3, 0)
_MAX_ITEMS = 100_000
_MAX_TEXT = 512
_MAX_TITLE = 1024
_SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie", "x-api-key", "x-auth-token"}
_SAFE_HEADERS = {"accept", "accept-language", "origin", "referer", "user-agent", "range"}
_SENSITIVE_QUERY = re.compile(
    r"(?:token|sig(?:nature)?|auth|key|policy|credential|expires?|session|jwt|secret)", re.I
)
_DIRECT_PROTOCOLS = {"http", "https"}
_PLAYLIST_TYPES = {"playlist", "multi_video"}


class YtDlpEngineError(RuntimeError):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        confidence: ErrorConfidence = ErrorConfidence.STRONG,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        if retryable is None:
            retryable = code in {ErrorCode.NETWORK_RESET, ErrorCode.NETWORK_TIMEOUT, ErrorCode.RATE_LIMITED}
        self.error = ErrorInstance(
            code=code,
            confidence=confidence,
            user_message_key=f"error.{code.value.lower()}",
            retryable=retryable,
        )


class YtDlpCancelled(RuntimeError):
    pass


class MediaExecutionMode(StrEnum):
    SIMPLE_DIRECT = "SIMPLE_DIRECT"
    CONTROLLED_MEDIA = "CONTROLLED_MEDIA"
    COMPAT_MEDIA = "COMPAT_MEDIA"


@dataclass(frozen=True, slots=True)
class MediaDiscoveryResult:
    source_kind: str
    presentation: MediaPresentationContract
    items: tuple[NormalizedItemDescriptor, ...]
    collection_identity: str | None = None
    collection_title: str | None = None
    reported_count: int | None = None
    completeness: str = "COMPLETE"


@dataclass(frozen=True, slots=True)
class MediaExecutionPlan:
    mode: MediaExecutionMode
    source_identity: str
    display_title: str
    output_filename: str
    presentation: MediaPresentationContract
    candidate_artifacts: tuple[CandidateArtifact, ...] = ()
    capabilities: ExecutionCapabilityProfile = field(default_factory=lambda: _compat_capabilities())
    sanitized_metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in {
            MediaExecutionMode.SIMPLE_DIRECT,
            MediaExecutionMode.CONTROLLED_MEDIA,
            MediaExecutionMode.COMPAT_MEDIA,
        }:
            raise ValueError("unsupported media execution mode")
        if not self.source_identity or not self.display_title or not self.output_filename:
            raise ValueError("media execution plan identity/title/output cannot be empty")
        object.__setattr__(self, "candidate_artifacts", tuple(self.candidate_artifacts))
        object.__setattr__(self, "sanitized_metadata", MappingProxyType(dict(self.sanitized_metadata)))


@dataclass(frozen=True, slots=True)
class ManagedDownloadResult:
    output_paths: tuple[Path, ...]
    info: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_paths", tuple(self.output_paths))
        object.__setattr__(self, "info", MappingProxyType(dict(self.info)))


class YtDlpBackend(Protocol):
    def probe_extractor(self, raw_input: str) -> tuple[str, bool] | None: ...
    def extract(self, raw_input: str, *, flat_playlist: bool) -> Mapping[str, Any]: ...
    def download(
        self,
        raw_input: str,
        *,
        output_dir: Path,
        options: Mapping[str, object],
        cancel_event: threading.Event,
    ) -> ManagedDownloadResult: ...


class _NullLogger:
    def debug(self, _msg: str) -> None: pass
    def info(self, _msg: str) -> None: pass
    def warning(self, _msg: str) -> None: pass
    def error(self, _msg: str) -> None: pass


def _version_key(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"0*(\d+)\.0*(\d+)\.0*(\d+)", value.strip())
    if not match:
        return None
    return tuple(int(group) for group in match.groups())  # type: ignore[return-value]


class YtDlpPythonBackend:
    """Lazy Worker-owned wrapper around yt-dlp's Python embedding API.

    No CLI configuration is parsed and stdout/progress output is suppressed because a source Worker
    may use stdio as its authenticated IPC transport. Raw extractor dictionaries never leave the
    adapter boundary.
    """

    @staticmethod
    def _verify_runtime(*, require_javascript: bool = False) -> None:
        try:
            installed = version("yt-dlp")
        except PackageNotFoundError as exc:
            raise YtDlpEngineError(ErrorCode.ENGINE_UNAVAILABLE, "yt-dlp is not installed") from exc
        if _version_key(installed) != _version_key(YT_DLP_PIN):
            raise YtDlpEngineError(
                ErrorCode.ENGINE_PROTOCOL_ERROR,
                f"yt-dlp version mismatch: expected {YT_DLP_PIN}, got {installed}",
                confidence=ErrorConfidence.EXACT,
                retryable=False,
            )
        if not require_javascript:
            return
        try:
            ejs = version("yt-dlp-ejs")
        except PackageNotFoundError as exc:
            raise YtDlpEngineError(ErrorCode.ENGINE_UNAVAILABLE, "yt-dlp EJS runtime package is not installed") from exc
        if _version_key(ejs) != _version_key(YT_DLP_EJS_PIN):
            raise YtDlpEngineError(
                ErrorCode.ENGINE_PROTOCOL_ERROR,
                f"yt-dlp-ejs version mismatch: expected {YT_DLP_EJS_PIN}, got {ejs}",
                confidence=ErrorConfidence.EXACT,
                retryable=False,
            )
        deno = shutil.which("deno")
        if deno is None:
            raise YtDlpEngineError(ErrorCode.ENGINE_UNAVAILABLE, "Deno JavaScript runtime is unavailable")
        try:
            probe = subprocess.run(
                [deno, "--version"], capture_output=True, text=True, timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise YtDlpEngineError(ErrorCode.ENGINE_UNAVAILABLE, "Deno JavaScript runtime probe failed") from exc
        first = (probe.stdout or probe.stderr).splitlines()
        match = re.search(r"\bdeno\s+(\d+)\.(\d+)\.(\d+)", first[0] if first else "", re.I)
        if probe.returncode != 0 or match is None:
            raise YtDlpEngineError(ErrorCode.ENGINE_PROTOCOL_ERROR, "Deno version output is invalid")
        current = tuple(int(group) for group in match.groups())
        if current < DENO_MIN_VERSION:
            floor = ".".join(str(v) for v in DENO_MIN_VERSION)
            raise YtDlpEngineError(
                ErrorCode.ENGINE_PROTOCOL_ERROR,
                f"Deno version is below the supported floor {floor}",
                confidence=ErrorConfidence.EXACT,
                retryable=False,
            )

    @staticmethod
    def _base_options() -> dict[str, object]:
        return {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _NullLogger(),
            "ignoreerrors": False,
            "allow_unplayable_formats": False,
            # Supply-chain boundary: EJS is supplied by the pinned local package. Do not let
            # yt-dlp fetch executable challenge components from npm/GitHub at runtime.
            "remote_components": set(),
        }

    def probe_extractor(self, raw_input: str) -> tuple[str, bool] | None:
        self._verify_runtime()
        try:
            from yt_dlp.extractor import gen_extractor_classes  # type: ignore[import-not-found]
            generic: tuple[str, bool] | None = None
            for ie in gen_extractor_classes():
                try:
                    if not ie.suitable(raw_input):
                        continue
                except Exception:
                    continue
                name = str(getattr(ie, "IE_NAME", getattr(ie, "__name__", "unknown")))
                is_generic = name.casefold() == "generic" or "generic" in str(getattr(ie, "__name__", "")).casefold()
                if not is_generic:
                    return name, False
                generic = (name, True)
            return generic
        except Exception as exc:
            raise _map_yt_exception(exc) from exc

    def extract(self, raw_input: str, *, flat_playlist: bool) -> Mapping[str, Any]:
        self._verify_runtime(require_javascript=_requires_javascript_runtime(raw_input))
        try:
            import yt_dlp  # type: ignore[import-not-found]
            options = self._base_options()
            if flat_playlist:
                options.update({"extract_flat": "in_playlist", "lazy_playlist": True})
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(raw_input, download=False)
                if not isinstance(info, Mapping):
                    raise YtDlpEngineError(
                        ErrorCode.ENGINE_PROTOCOL_ERROR,
                        "yt-dlp returned a non-mapping extraction result",
                        confidence=ErrorConfidence.STRONG,
                        retryable=False,
                    )
                return info
        except YtDlpEngineError:
            raise
        except Exception as exc:
            raise _map_yt_exception(exc) from exc

    def download(
        self,
        raw_input: str,
        *,
        output_dir: Path,
        options: Mapping[str, object],
        cancel_event: threading.Event,
    ) -> ManagedDownloadResult:
        self._verify_runtime(require_javascript=_requires_javascript_runtime(raw_input))
        output_dir.mkdir(parents=True, exist_ok=True)
        seen_paths: list[Path] = []

        def progress_hook(status: Mapping[str, Any]) -> None:
            if cancel_event.is_set():
                raise YtDlpCancelled("managed media cancellation requested")
            filename = status.get("filename")
            if isinstance(filename, str) and filename:
                path = Path(filename)
                if path not in seen_paths:
                    seen_paths.append(path)

        try:
            import yt_dlp  # type: ignore[import-not-found]
            runtime_options = self._base_options()
            runtime_options.update(dict(options))
            runtime_options.update({
                "paths": {"home": str(output_dir), "temp": str(output_dir)},
                "outtmpl": {"default": str(output_dir / "%(id)s.%(ext)s")},
                "progress_hooks": [progress_hook],
            })
            with yt_dlp.YoutubeDL(runtime_options) as ydl:
                info = ydl.extract_info(raw_input, download=True)
                if cancel_event.is_set():
                    raise YtDlpCancelled("managed media cancellation requested")
                if not isinstance(info, Mapping):
                    raise YtDlpEngineError(
                        ErrorCode.ENGINE_PROTOCOL_ERROR,
                        "yt-dlp returned a non-mapping download result",
                        confidence=ErrorConfidence.STRONG,
                        retryable=False,
                    )
                safe = _safe_metadata(info)
                # sanitize_info is a serializability aid, not a secret filter. We deliberately expose
                # only our allow-list above and use sanitize_info only as a runtime API contract smoke.
                ydl.sanitize_info(dict(safe))
                requested = info.get("requested_downloads")
                if isinstance(requested, Sequence) and not isinstance(requested, (str, bytes)):
                    for row in requested:
                        if isinstance(row, Mapping):
                            filepath = row.get("filepath") or row.get("filename")
                            if isinstance(filepath, str) and filepath:
                                path = Path(filepath)
                                if path not in seen_paths:
                                    seen_paths.append(path)
                filepath = info.get("filepath") or info.get("_filename")
                if isinstance(filepath, str) and filepath:
                    path = Path(filepath)
                    if path not in seen_paths:
                        seen_paths.append(path)
                return ManagedDownloadResult(tuple(seen_paths), safe)
        except YtDlpCancelled:
            raise
        except Exception as exc:
            if cancel_event.is_set():
                raise YtDlpCancelled("managed media cancellation requested") from exc
            raise _map_yt_exception(exc) from exc



def _requires_javascript_runtime(raw_input: str) -> bool:
    try:
        host = (urlsplit(raw_input).hostname or "").casefold().rstrip(".")
    except ValueError:
        return False
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")

def _map_yt_exception(exc: BaseException) -> YtDlpEngineError:
    name = type(exc).__name__.casefold()
    text = str(exc).casefold()
    if "drm" in text:
        code = ErrorCode.DRM_PROTECTED
    elif any(token in text for token in ("login", "sign in", "cookie", "authentication", "private video")):
        code = ErrorCode.AUTH_REQUIRED
    elif any(token in text for token in ("geo", "not available in your country", "region")):
        code = ErrorCode.GEO_RESTRICTED
    elif "429" in text or "rate limit" in text or "too many requests" in text:
        code = ErrorCode.RATE_LIMITED
    elif "timeout" in name or "timed out" in text:
        code = ErrorCode.NETWORK_TIMEOUT
    elif any(token in text for token in ("connection", "network", "reset by peer")):
        code = ErrorCode.NETWORK_RESET
    elif any(token in text for token in ("unsupported url", "no suitable extractor")):
        code = ErrorCode.UNSUPPORTED_MEDIA
    elif any(token in text for token in ("not found", "unavailable", "404")):
        code = ErrorCode.SOURCE_NOT_FOUND
    else:
        code = ErrorCode.ENGINE_UNKNO…667 tokens truncated…      return True
    extractor = _extractor_name(info)
    if "channel" in extractor and "playlist" not in extractor:
        return True
    redacted = _redacted_url(_text(info.get("webpage_url") or raw_input, limit=4096)).casefold()
    return any(part in redacted for part in ("/channel/", "/user/", "/c/", "/@")) and "list=" not in redacted


def _safe_metadata(info: Mapping[str, Any]) -> dict[str, object]:
    allowed = (
        "id", "extractor", "extractor_key", "uploader", "uploader_id", "channel", "channel_id",
        "upload_date", "timestamp", "duration", "width", "height", "fps", "ext", "format_id",
        "playlist_id", "playlist_index", "n_entries", "live_status",
    )
    result: dict[str, object] = {}
    for key in allowed:
        value = info.get(key)
        if isinstance(value, str):
            result[key] = _text(value)
        elif isinstance(value, (int, float, bool)) or value is None:
            result[key] = value
    return result


def _normalized_item(info: Mapping[str, Any], *, raw_input: str, sequence: int) -> NormalizedItemDescriptor:
    title = _text(info.get("title") or info.get("fulltitle") or info.get("id") or "Media", limit=_MAX_TITLE)
    index = _positive_int(info.get("playlist_index"))
    if index is None:
        index = sequence
    width = _positive_int(info.get("width"))
    height = _positive_int(info.get("height"))
    return NormalizedItemDescriptor(
        source_identity=_source_identity(info, raw_input),
        media_kind="MEDIA",
        display_title=title,
        source_index=index,
        discovery_sequence=sequence,
        width=width,
        height=height,
        sanitized_metadata=_safe_metadata(info),
    )


def _safe_filename(info: Mapping[str, Any], *, fallback: str = "media") -> str:
    title = _text(info.get("title") or info.get("id") or fallback, limit=180)
    ext = _text(info.get("ext"), limit=16).lower().lstrip(".") or "bin"
    title = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", PurePath(title).name).strip(" .") or fallback
    return f"{title}.{ext}"[:240]


def _format_descriptor(fmt: Mapping[str, Any]) -> TransferDescriptor:
    raw_url = fmt.get("url")
    if not isinstance(raw_url, str) or not raw_url:
        return TransferDescriptor(url="invalid://missing", handoff_safety=HandoffSafety.UNSAFE)
    try:
        parts = urlsplit(raw_url)
    except ValueError:
        return TransferDescriptor(url=raw_url, handoff_safety=HandoffSafety.UNSAFE)
    protocol = _text(fmt.get("protocol"), limit=40).casefold()
    has_fragments = isinstance(fmt.get("fragments"), Sequence) and not isinstance(fmt.get("fragments"), (str, bytes))
    if parts.scheme not in _DIRECT_PROTOCOLS or not parts.hostname or protocol not in _DIRECT_PROTOCOLS or has_fragments:
        return TransferDescriptor(url=raw_url, handoff_safety=HandoffSafety.UNSAFE)

    raw_headers = fmt.get("http_headers") or {}
    if not isinstance(raw_headers, Mapping):
        raw_headers = {}
    headers = {str(k): str(v) for k, v in raw_headers.items() if v is not None}
    lower = {k.casefold(): v for k, v in headers.items()}
    secret = bool(_SECRET_HEADERS & lower.keys())
    unknown = {key for key in lower if key not in _SAFE_HEADERS and key not in _SECRET_HEADERS}
    sensitive_query = any(_SENSITIVE_QUERY.search(key) for key, _ in parse_qsl(parts.query, keep_blank_values=True))
    if secret:
        safety = HandoffSafety.UNSAFE
    elif headers or unknown or sensitive_query:
        safety = HandoffSafety.CONDITIONAL
    else:
        safety = HandoffSafety.SAFE
    return TransferDescriptor(
        url=raw_url,
        headers=headers,
        referer=lower.get("referer"),
        expected_size=_positive_int(fmt.get("filesize")) or _positive_int(fmt.get("filesize_approx")),
        content_type=_text(fmt.get("http_headers", {}).get("Content-Type") if isinstance(fmt.get("http_headers"), Mapping) else None) or None,
        origin_scope=f"{parts.scheme}://{parts.hostname}",
        redirect_policy="HTTPS_ONLY" if parts.scheme == "https" else "HTTP_OR_HTTPS",
        resume_semantics="VALIDATOR_REQUIRED",
        handoff_safety=safety,
    )


def _has_audio(fmt: Mapping[str, Any]) -> bool:
    return _text(fmt.get("acodec"), limit=40).casefold() not in {"", "none"}


def _has_video(fmt: Mapping[str, Any]) -> bool:
    return _text(fmt.get("vcodec"), limit=40).casefold() not in {"", "none"}


def _candidate(fmt: Mapping[str, Any], role: str, sequence: int) -> CandidateArtifact:
    descriptor = _format_descriptor(fmt)
    ext = _text(fmt.get("ext"), limit=16).lower().lstrip(".") or "bin"
    return CandidateArtifact(
        role=role,
        suggested_filename=f"{role.casefold()}-{sequence}.{ext}",
        descriptor=descriptor,
        expected_size=descriptor.expected_size,
        content_type=descriptor.content_type,
    )


def _simple_capabilities(safety: HandoffSafety) -> ExecutionCapabilityProfile:
    return ExecutionCapabilityProfile(
        transfer_control=CapabilityLevel.EXACT,
        network_parallelism_control=CapabilityLevel.EXACT,
        progress_control=CapabilityLevel.EXACT,
        postprocess_control=CapabilityLevel.UNSUPPORTED,
        pause_semantics=PauseSemantics.CHECKPOINT,
        resume_control=ResumeControl.V10_CHECKPOINT,
        direct_handoff=safety,
    )


def _controlled_capabilities(safety: HandoffSafety) -> ExecutionCapabilityProfile:
    return ExecutionCapabilityProfile(
        transfer_control=CapabilityLevel.EXACT,
        network_parallelism_control=CapabilityLevel.EXACT,
        progress_control=CapabilityLevel.BEST_EFFORT,
        postprocess_control=CapabilityLevel.EXACT,
        pause_semantics=PauseSemantics.RESTART_PHASE,
        resume_control=ResumeControl.RESTART_OPERATION,
        direct_handoff=safety,
    )


def _compat_capabilities(network_level: ManagedNetworkControlLevel = ManagedNetworkControlLevel.BEST_EFFORT) -> ExecutionCapabilityProfile:
    level_map = {
        ManagedNetworkControlLevel.EXACT: CapabilityLevel.EXACT,
        ManagedNetworkControlLevel.CONFIGURABLE: CapabilityLevel.CONFIGURABLE,
        ManagedNetworkControlLevel.BEST_EFFORT: CapabilityLevel.BEST_EFFORT,
        ManagedNetworkControlLevel.OPAQUE: CapabilityLevel.OPAQUE,
    }
    return ExecutionCapabilityProfile(
        transfer_control=CapabilityLevel.BEST_EFFORT,
        network_parallelism_control=level_map[network_level],
        progress_control=CapabilityLevel.BEST_EFFORT,
        postprocess_control=CapabilityLevel.BEST_EFFORT,
        pause_semantics=PauseSemantics.RESTART_PHASE,
        resume_control=ResumeControl.ENGINE_MANAGED,
        direct_handoff=HandoffSafety.UNSAFE,
    )


def options_from_policy(policy: ManagedMediaExecutionPolicy) -> Mapping[str, object]:
    """Translate Gate-6.5 resource/retry policy to bounded yt-dlp options."""

    inner_retries = max(0, policy.retry.inner_operation_attempt_limit - 1)
    options: dict[str, object] = {
        "retries": inner_retries,
        "fragment_retries": inner_retries,
        "extractor_retries": inner_retries,
        "file_access_retries": min(inner_retries, 2),
    }
    if policy.network.control_level is not ManagedNetworkControlLevel.OPAQUE:
        assert policy.network.granted_parallelism is not None
        options["concurrent_fragment_downloads"] = policy.network.granted_parallelism
    return MappingProxyType(options)


class YtDlpAdapter:
    adapter_id = "yt-dlp"

    def __init__(self, backend: YtDlpBackend | None = None) -> None:
        self._backend = backend or YtDlpPythonBackend()

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            parallelism=CapabilityLevel.CONFIGURABLE,
            pause_resume=CapabilityLevel.BEST_EFFORT,
            exact_progress=CapabilityLevel.BEST_EFFORT,
        )

    def probe(self, raw_input: str) -> ProbeResult:
        try:
            parts = urlsplit(raw_input)
        except ValueError:
            return ProbeResult(ProbeSupport.NO, 1.0, reason="invalid URL")
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return ProbeResult(ProbeSupport.NO, 1.0, reason="yt-dlp requires an HTTP(S) source")
        found = self._backend.probe_extractor(raw_input)
        if found is None:
            return ProbeResult(ProbeSupport.NO, 0.99, specificity=90, reason="no yt-dlp extractor matched")
        name, generic = found
        return ProbeResult(
            ProbeSupport.MAYBE if generic else ProbeSupport.YES,
            0.65 if generic else 0.99,
            specificity=20 if generic else 95,
            cost_class="LOW",
            requires_network_probe=generic,
            reason=f"yt-dlp:{name}",
        )

    def discover(self, raw_input: str) -> MediaDiscoveryResult:
        info = self._backend.extract(raw_input, flat_playlist=True)
        root_type = _text(info.get("_type"), limit=40).casefold()
        if root_type in _PLAYLIST_TYPES:
            presentation = MediaPresentationContract.channel() if _is_channel(info, raw_input) else MediaPresentationContract.playlist()
            entries = info.get("entries")
            if entries is None:
                rows: Sequence[Any] = ()
            elif isinstance(entries, Sequence) and not isinstance(entries, (str, bytes)):
                rows = entries
            else:
                # yt-dlp lazy playlists can expose an iterable that is not a Sequence.
                rows = entries  # type: ignore[assignment]
            items: list[NormalizedItemDescriptor] = []
            for entry in rows:
                if entry is None or not isinstance(entry, Mapping):
                    continue
                items.append(_normalized_item(entry, raw_input=raw_input, sequence=len(items)))
                if len(items) > _MAX_ITEMS:
                    raise YtDlpEngineError(ErrorCode.RESOURCE_EXHAUSTED, "media collection item ceiling exceeded")
            reported = _positive_int(info.get("playlist_count")) or _positive_int(info.get("n_entries"))
            return MediaDiscoveryResult(
                source_kind="MEDIA_COLLECTION",
                presentation=presentation,
                items=tuple(items),
                collection_identity=_collection_identity(info, raw_input),
                collection_title=_text(info.get("title") or info.get("playlist_title") or "Media collection", limit=_MAX_TITLE),
                reported_count=reported,
                completeness="PARTIAL" if reported is None else "COMPLETE",
            )
        item = _normalized_item(info, raw_input=raw_input, sequence=0)
        return MediaDiscoveryResult(
            source_kind="SINGLE_MEDIA",
            presentation=MediaPresentationContract.single_media(),
            items=(item,),
            reported_count=1,
        )

    def resolve(self, raw_input: str, policy: ManagedMediaExecutionPolicy) -> MediaExecutionPlan:
        info = self._backend.extract(raw_input, flat_playlist=False)
        return self.plan_from_info(info, raw_input=raw_input, policy=policy)

    def plan_from_info(
        self,
        info: Mapping[str, Any],
        *,
        raw_input: str,
        policy: ManagedMediaExecutionPolicy,
    ) -> MediaExecutionPlan:
        source_identity = _source_identity(info, raw_input)
        title = _text(info.get("title") or info.get("fulltitle") or info.get("id") or "Media", limit=_MAX_TITLE)
        output = _safe_filename(info)
        presentation = MediaPresentationContract.single_media()

        requested = info.get("requested_formats")
        if isinstance(requested, Sequence) and not isinstance(requested, (str, bytes)):
            formats = [row for row in requested if isinstance(row, Mapping)]
        else:
            formats = []

        if not formats and isinstance(info.get("url"), str):
            formats = [info]

        # One progressive format carrying both audio and video can be handed directly to the already
        # verified DirectHTTP/FileCommit path, but only when the descriptor is handoff-safe.
        if len(formats) == 1 and _has_audio(formats[0]) and _has_video(formats[0]):
            candidate = _candidate(formats[0], "PRIMARY", 0)
            if candidate.descriptor.handoff_safety is not HandoffSafety.UNSAFE:
                return MediaExecutionPlan(
                    mode=MediaExecutionMode.SIMPLE_DIRECT,
                    source_identity=source_identity,
                    display_title=title,
                    output_filename=output,
                    presentation=presentation,
                    candidate_artifacts=(CandidateArtifact(
                        role="PRIMARY",
                        suggested_filename=output,
                        descriptor=candidate.descriptor,
                        expected_size=candidate.expected_size,
                        content_type=candidate.content_type,
                    ),),
                    capabilities=_simple_capabilities(candidate.descriptor.handoff_safety),
                    sanitized_metadata=_safe_metadata(info),
                )

        video = next((fmt for fmt in formats if _has_video(fmt) and not _has_audio(fmt)), None)
        audio = next((fmt for fmt in formats if _has_audio(fmt) and not _has_video(fmt)), None)
        if video is not None and audio is not None:
            video_candidate = _candidate(video, "VIDEO", 0)
            audio_candidate = _candidate(audio, "AUDIO", 1)
            candidates = (video_candidate, audio_candidate)
            if all(candidate.descriptor.handoff_safety is not HandoffSafety.UNSAFE for candidate in candidates):
                safety = (
                    HandoffSafety.CONDITIONAL
                    if any(candidate.descriptor.handoff_safety is HandoffSafety.CONDITIONAL for candidate in candidates)
                    else HandoffSafety.SAFE
                )
                return MediaExecutionPlan(
                    mode=MediaExecutionMode.CONTROLLED_MEDIA,
                    source_identity=source_identity,
                    display_title=title,
                    output_filename=output,
                    presentation=presentation,
                    candidate_artifacts=candidates,
                    capabilities=_controlled_capabilities(safety),
                    sanitized_metadata=_safe_metadata(info),
                )

        # Fragmented/manifest/secret-bound/unknown pipelines stay in yt-dlp managed mode. We report
        # only the network control level actually granted by Core, never EXACT by inference.
        return MediaExecutionPlan(
            mode=MediaExecutionMode.COMPAT_MEDIA,
            source_identity=source_identity,
            display_title=title,
            output_filename=output,
            presentation=presentation,
            candidate_artifacts=(),
            capabilities=_compat_capabilities(policy.network.control_level),
            sanitized_metadata=_safe_metadata(info),
        )

    def execute_compat(
        self,
        raw_input: str,
        *,
        output_dir: Path,
        policy: ManagedMediaExecutionPolicy,
        cancel_event: threading.Event,
    ) -> ManagedDownloadResult:
        return self._backend.download(
            raw_input,
            output_dir=output_dir,
            options=options_from_policy(policy),
            cancel_event=cancel_event,
        )
