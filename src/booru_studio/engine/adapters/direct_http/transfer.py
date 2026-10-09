from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from types import MappingProxyType
from typing import Mapping

import requests

from booru_studio.common.clock import Clock, SystemClock
from booru_studio.common.hashing import fsync_file, sha256_file
from booru_studio.common.ids import ArtifactId
from booru_studio.common.random_source import RandomSource, SystemRandomSource
from booru_studio.common.paths import reject_symlink
from booru_studio.scheduler.coordinator import NetworkAdmissionController
from booru_studio.engine.network_scope import (
    NetworkScopeBlocked, NetworkScopePolicyMode, authorize_transfer_url, normalized_origin,
)
from booru_studio.scheduler.retry import RetryPolicy, parse_retry_after_seconds, transient_network_reason
from booru_studio.worker.resume import recover_resume_checkpoint, write_resume_sidecar

_CHUNK_SIZE = 256 * 1024
_TRANSIENT_STATUS = {408, 425, 500, 502, 503, 504}
_SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie", "x-api-key", "x-auth-token"}
_HOP_HEADERS = {
    "host", "connection", "proxy-connection", "keep-alive", "transfer-encoding",
    "te", "trailer", "upgrade", "content-length",
}


class TransferCancelled(RuntimeError):
    pass


class RetryableTransferError(RuntimeError):
    pass


class SourceChangedError(RuntimeError):
    pass


class RateLimitedError(RetryableTransferError):
    def __init__(self, status: int, retry_after_s: float) -> None:
        super().__init__(f"HTTP {status}; retry after {retry_after_s:.3f}s")
        self.status = status
        self.retry_after_s = retry_after_s


@dataclass(frozen=True, slots=True)
class DirectHttpTransfer:
    artifact_id: ArtifactId
    generation: int
    url: str
    staging_path: Path
    sidecar_path: Path
    source_fingerprint: str
    headers: Mapping[str, str] = field(default_factory=dict)
    expected_size: int | None = None
    expected_sha256: bytes | None = None
    timeout_s: float = 30.0
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    checkpoint_bytes: int = 4 * 1024 * 1024
    checkpoint_interval_s: float = 2.0
    redirect_policy: str = "HTTP_OR_HTTPS"
    network_scope_policy: str = "ANY"
    network_scope_root: str | None = None

    def __post_init__(self) -> None:
        if not self.url.startswith(("http://", "https://")):
            raise ValueError("DirectHTTP only accepts http(s) URLs")
        if self.generation < 0:
            raise ValueError("generation cannot be negative")
        if self.expected_size is not None and self.expected_size < 0:
            raise ValueError("expected_size cannot be negative")
        if self.expected_sha256 is not None and len(self.expected_sha256) != 32:
            raise ValueError("expected_sha256 must be 32 bytes")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if self.checkpoint_bytes <= 0 or self.checkpoint_interval_s <= 0:
            raise ValueError("checkpoint settings must be positive")
        if self.redirect_policy not in {"SAME_ORIGIN", "HTTPS_ONLY", "HTTP_OR_HTTPS"}:
            raise ValueError("unsupported redirect policy")
        try:
            NetworkScopePolicyMode(self.network_scope_policy)
        except ValueError as exc:
            raise ValueError("unsupported network scope policy") from exc
        if self.network_scope_policy == NetworkScopePolicyMode.ROOT_OR_PUBLIC.value and not self.network_scope_root:
            raise ValueError("ROOT_OR_PUBLIC requires network_scope_root")
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


@dataclass(frozen=True, slots=True)
class DirectHttpTransferResult:
    artifact_id: ArtifactId
    staging_path: Path
    sidecar_path: Path
    size_bytes: int
    sha256: bytes
    resumed_from: int
    attempts: int
    effective_url_host: str
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True, slots=True)
class _ResumeCheckpoint:
    size: int
    validator: str
    total: int | None


def _strong_etag(headers: Mapping[str, str]) -> str:
    value = str(headers.get("ETag") or "").strip()
    return "" if value.upper().startswith("W/") else value


def _response_validator(headers: Mapping[str, str]) -> str:
    return _strong_etag(headers) or str(headers.get("Last-Modified") or "").strip()


def _usable_validator(value: str) -> bool:
    return bool(value and not value.upper().startswith("W/"))


def _content_range(value: str) -> tuple[int, int, int | None] | None:
    match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", value.strip(), re.I)
    if match is None:
        return None
    start, end = int(match.group(1)), int(match.group(2))
    total = None if match.group(3) == "*" else int(match.group(3))
    return start, end, total


def _sleep_cancelable(cancel_event: threading.Event, seconds: float) -> None:
    if seconds <= 0:
        return
    if cancel_event.wait(seconds):
        raise TransferCancelled("transfer cancelled")


def _safe_unlink(path: Path) -> None:
    try:
        reject_symlink(path)
        path.unlink(missing_ok=True)
    except FileNotFoundError:
        return


class DirectHttpWorker:
    """One-thread DirectHTTP worker owning one Requests Session."""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        random_source: RandomSource | None = None,
        user_agent: str = "BooruStudio/10.0",
    ) -> None:
        self.clock = clock or SystemClock()
        self.random = random_source or SystemRandomSource()
        self.session = requests.Session()
        # Prevent ambient .netrc credentials from being injected into arbitrary origins.
        self.session.trust_env = False
        self.session.headers.update({"User-Agent": user_agent, "Accept": "*/*"})

    def close(self) -> None:
        self.session.close()

    def __call__(
        self,
        transfer: DirectHttpTransfer,
        cancel_event: threading.Event,
        admission: NetworkAdmissionController,
    ) -> DirectHttpTransferResult:
        return self.transfer(transfer, cancel_event, admission)

    @staticmethod
    def _headers(transfer: DirectHttpTransfer) -> dict[str, str]:
        headers = {str(key): str(value) for key, value in transfer.headers.items() if value is not None}
        for key in tuple(headers):
            if key.lower() in _SECRET_HEADERS | _HOP_HEADERS:
                headers.pop(key, None)
        headers.setdefault("Accept", "*/*")
        headers["Accept-Encoding"] = "identity"
        return headers

    @staticmethod
    def _redirect_allowed(transfer: DirectHttpTransfer, initial_url: str, target_url: str) -> bool:
        try:
            target = urlsplit(target_url)
            if target.scheme not in {"http", "https"}:
                return False
            if transfer.redirect_policy == "HTTPS_ONLY" and target.scheme != "https":
                return False
            if transfer.redirect_policy == "SAME_ORIGIN" and normalized_origin(initial_url) != normalized_origin(target_url):
                return False
            return True
        except (ValueError, NetworkScopeBlocked):
            return False

    def _request_with_redirect_policy(
        self,
        transfer: DirectHttpTransfer,
        *,
        headers: Mapping[str, str],
        proxies: Mapping[str, str],
        verify: bool | str,
    ) -> requests.Response:
        current = transfer.url
        mode = NetworkScopePolicyMode(transfer.network_scope_policy)
        for _ in range(11):
            try:
                authorize_transfer_url(
                    current, mode=mode, root_url=transfer.network_scope_root,
                )
            except NetworkScopeBlocked as exc:
                raise RuntimeError("DirectHTTP destination blocked by network-scope policy") from exc
            response = self.session.get(
                current, stream=True, headers=dict(headers), timeout=transfer.timeout_s,
                allow_redirects=False, proxies=dict(proxies), verify=verify,
            )
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("Location")
            if not location:
                return response
            target = urljoin(current, location)
            if not self._redirect_allowed(transfer, transfer.url, target):
                response.close()
                raise RuntimeError("DirectHTTP redirect blocked by redirect policy")
            response.close()
            current = target
        raise RuntimeError("DirectHTTP redirect ceiling exceeded")

    def _load_resume(self, transfer: DirectHttpTransfer) -> _ResumeCheckpoint:
        if not transfer.staging_path.exists() or not transfer.sidecar_path.exists():
            return _ResumeCheckpoint(0, "", None)
        try:
            state = recover_resume_checkpoint(transfer.sidecar_path)
        except (OSError, ValueError, KeyError):
            _safe_unlink(transfer.staging_path)
            _safe_unlink(transfer.sidecar_path)
            return _ResumeCheckpoint(0, "", None)
        if state.artifact_id != transfer.artifact_id or state.generation != transfer.generation:
            _safe_unlink(transfer.staging_path)
            _safe_unlink(transfer.sidecar_path)
            return _ResumeCheckpoint(0, "", None)
        if state.source_fingerprint != transfer.source_fingerprint:
            _safe_unlink(transfer.staging_path)
            _safe_unlink(transfer.sidecar_path)
            return _ResumeCheckpoint(0, "", None)
        validator = str(state.validator.get("if_range") or "").strip()
        if state.part_size > 0 and not _usable_validator(validator):
            _safe_unlink(transfer.staging_path)
            _safe_unlink(transfer.sidecar_path)
            return _ResumeCheckpoint(0, "", None)
        raw_total = state.validator.get("total")
        total = int(raw_total) if isinstance(raw_total, int) and raw_total >= 0 else None
        return _ResumeCheckpoint(state.part_size, validator, total)

    def _checkpoint(
        self,
        transfer: DirectHttpTransfer,
        *,
        validator: str,
        etag: str,
        last_modified: str,
        total: int | None,
    ) -> None:
        fsync_file(transfer.staging_path)
        write_resume_sidecar(
            artifact_id=transfer.artifact_id,
            generation=transfer.generation,
            part_path=transfer.staging_path,
            sidecar_path=transfer.sidecar_path,
            source_fingerprint=transfer.source_fingerprint,
            validator={
                "if_range": validator,
                "etag": etag,
                "last_modified": last_modified,
                "total": total,
            },
        )

    def transfer(
        self,
        transfer: DirectHttpTransfer,
        cancel_event: threading.Event,
        admission: NetworkAdmissionController,
    ) -> DirectHttpTransferResult:
        transfer.staging_path.parent.mkdir(parents=True, exist_ok=True)
        reject_symlink(transfer.staging_path)
        reject_symlink(transfer.sidecar_path)
        failures = 0
        attempts = 0
        successful_resumed_from = 0
        protocol_clean_retry_available = True

        while True:
            if cancel_event.is_set():
                raise TransferCancelled("transfer cancelled")
            resume = self._load_resume(transfer)
            attempts += 1
            headers = self._headers(transfer)
            if resume.size:
                headers["Range"] = f"bytes={resume.size}-"
                headers["If-Range"] = resume.validator

            response: requests.Response | None = None
            effective_url = transfer.url
            try:
                with admission.request(transfer.url, cancel_event):
                    proxies = requests.utils.get_environ_proxies(transfer.url)
                    verify: bool | str = (
                        os.environ.get("REQUESTS_CA_BUNDLE")
                        or os.environ.get("CURL_CA_BUNDLE")
                        or True
                    )
                    response = self._request_with_redirect_policy(
                        transfer, headers=headers, proxies=proxies, verify=verify,
                    )
                    effective_url = str(response.url or transfer.url)
                    status = int(response.status_code)
                    if status == 429 or (status == 503 and response.headers.get("Retry-After")):
                        retry_after = parse_retry_after_seconds(
                            response.headers, now_utc_ms=self.clock.utc_ms(), fallback_s=1.0
                        )
                        raise RateLimitedError(status, retry_after)
                    if status in _TRANSIENT_STATUS:
                        raise RetryableTransferError(f"HTTP {status} {response.reason}")
                    if status == 416 and resume.size:
                        response.close(); response = None
                        _safe_unlink(transfer.staging_path); _safe_unlink(transfer.sidecar_path)
                        if protocol_clean_retry_available:
                            protocol_clean_retry_available = False
                            continue
                        raise SourceChangedError("HTTP 416 while resuming")
                    if status not in {200, 206}:
                        raise RuntimeError(f"HTTP {status} {response.reason}")
                    encoding = str(response.headers.get("Content-Encoding") or "").strip().lower()
                    if encoding not in {"", "identity"}:
                        raise RuntimeError(f"unexpected Content-Encoding: {encoding}")
                    if status == 206 and not resume.size:
                        raise SourceChangedError("unexpected HTTP 206 without Range request")

                    etag = _strong_etag(response.headers)
                    last_modified = str(response.headers.get("Last-Modified") or "").strip()
                    response_validator = etag or last_modified
                    total: int | None = None
                    mode = "wb"
                    base_size = 0
                    if resume.size and status == 206:
                        parsed = _content_range(str(response.headers.get("Content-Range") or ""))
                        if parsed is None:
                            raise SourceChangedError("invalid Content-Range")
                        range_start, range_end, total = parsed
                        if range_start != resume.size or range_end < range_start:
                            raise SourceChangedError("Content-Range does not match local partial")
                        validators = {value for value in (etag, last_modified) if value}
                        if resume.validator not in validators:
                            raise SourceChangedError("206 did not confirm If-Range validator")
                        if total is not None and total <= range_end:
                            raise SourceChangedError("invalid Content-Range total")
                        if resume.total is not None and total is not None and resume.total != total:
                            raise SourceChangedError("remote object size changed")
                        mode = "ab"
                        base_size = resume.size
                        successful_resumed_from = resume.size
                        response_validator = resume.validator
                    elif resume.size and status == 200:
                        # RFC If-Range mismatch or Range ignored: the 200 body is a clean full
                        # representation. Overwrite the stale partial rather than append.
                        base_size = 0
                        successful_resumed_from = 0
                    length = str(response.headers.get("Content-Length") or "")
                    if total is None and length.isdigit():
                        total = int(length) + (base_size if status == 206 else 0)

                    downloaded = base_size
                    last_checkpoint_bytes = downloaded
                    last_checkpoint_at = time.monotonic()
                    with transfer.staging_path.open(mode) as handle:
                        for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                            if cancel_event.is_set():
                                raise TransferCancelled("transfer cancelled")
                            if not chunk:
                                continue
                            handle.write(chunk)
                            downloaded += len(chunk)
                            now = time.monotonic()
                            if (
                                downloaded - last_checkpoint_bytes >= transfer.checkpoint_bytes
                                or now - last_checkpoint_at >= transfer.checkpoint_interval_s
                            ):
                                handle.flush(); os.fsync(handle.fileno())
                                self._checkpoint(
                                    transfer,
                                    validator=response_validator,
                                    etag=etag,
                                    last_modified=last_modified,
                                    total=total,
                                )
                                last_checkpoint_bytes = downloaded
                                last_checkpoint_at = now
                        handle.flush(); os.fsync(handle.fileno())

                    actual = transfer.staging_path.stat().st_size
                    self._checkpoint(
                        transfer,
                        validator=response_validator,
                        etag=etag,
                        last_modified=last_modified,
                        total=total,
                    )
                    if actual <= 0:
                        raise RetryableTransferError("empty response body")
                    if total is not None and actual != total:
                        raise RetryableTransferError(f"incomplete body ({actual}/{total})")
                    if transfer.expected_size is not None and actual != transfer.expected_size:
                        raise SourceChangedError(
                            f"expected size {transfer.expected_size}, received {actual}"
                        )
                    digest = sha256_file(transfer.staging_path)
                    if transfer.expected_sha256 is not None and digest != transfer.expected_sha256:
                        raise SourceChangedError("SHA-256 mismatch")
                    admission.report_success(effective_url)
                    return DirectHttpTransferResult(
                        artifact_id=transfer.artifact_id,
                        staging_path=transfer.staging_path,
                        sidecar_path=transfer.sidecar_path,
                        size_bytes=actual,
                        sha256=digest,
                        resumed_from=successful_resumed_from,
                        attempts=attempts,
                        effective_url_host=admission.host_limiter.host_key(effective_url),
                        etag=etag or None,
                        last_modified=last_modified or None,
                    )
            except TransferCancelled:
                raise
            except RateLimitedError as exc:
                failures += 1
                if not transfer.retry_policy.can_retry(failures):
                    raise
                _sleep_cancelable(cancel_event, exc.retry_after_s)
            except SourceChangedError:
                failures += 1
                _safe_unlink(transfer.staging_path); _safe_unlink(transfer.sidecar_path)
                if not transfer.retry_policy.can_retry(failures):
                    raise
                delay = transfer.retry_policy.delay_seconds(failures, self.random)
                _sleep_cancelable(cancel_event, delay)
            except RetryableTransferError:
                failures += 1
                if not transfer.retry_policy.can_retry(failures):
                    raise
                delay = transfer.retry_policy.delay_seconds(failures, self.random)
                _sleep_cancelable(cancel_event, delay)
            except BaseException as exc:
                reason = transient_network_reason(exc)
                if reason is None:
                    raise
                failures += 1
                admission.report_transient_failure(effective_url)
                if not transfer.retry_policy.can_retry(failures):
                    raise
                delay = transfer.retry_policy.delay_seconds(failures, self.random)
                _sleep_cancelable(cancel_event, delay)
            finally:
                if response is not None:
                    response.close()
