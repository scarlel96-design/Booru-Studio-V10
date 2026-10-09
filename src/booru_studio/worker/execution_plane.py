from __future__ import annotations

import hashlib
import threading
from concurrent.futures import as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from booru_studio.common.ids import ArtifactId
from booru_studio.engine.adapters.direct_http import DirectHttpTransfer, DirectHttpWorker
from booru_studio.scheduler.coordinator import ParallelTransferScheduler
from booru_studio.scheduler.retry import RetryPolicy


@dataclass(frozen=True, slots=True)
class DirectHttpExecutionOutcome:
    transfer_count: int
    configured_parallelism: int
    peak_network_active: int


class DirectHttpExecutionPlane:
    """Blocking engine execution plane; never owns the Worker IPC connection.

    Completed transfers are emitted progressively through ``on_staged`` so the
    control plane can drive FileCommit while other network requests are still active.
    This avoids waiting for an entire multi-file run before final files become durable.
    """

    _MAX_INLINE_TRANSFERS = 4096

    def run(
        self,
        execution_plan: dict[str, object],
        *,
        cancel_event: threading.Event,
        on_staged: Callable[[dict[str, object]], None] | None = None,
        operation_gate: threading.Event | None = None,
    ) -> DirectHttpExecutionOutcome:
        if str(execution_plan.get("mode") or "") != "DIRECT_HTTP":
            raise ValueError("unsupported execution mode")
        parallelism = int(execution_plan.get("parallelism") or 1)
        if not 1 <= parallelism <= 64:
            raise ValueError("parallelism outside supported range")
        raw_transfers = execution_plan.get("transfers")
        if not isinstance(raw_transfers, list) or not raw_transfers:
            raise ValueError("DIRECT_HTTP execution requires transfers")
        if len(raw_transfers) > self._MAX_INLINE_TRANSFERS:
            raise ValueError("inline DIRECT_HTTP plan exceeds bounded transfer count")
        transfers = [self._decode_transfer(obj) for obj in raw_transfers]
        scheduler = ParallelTransferScheduler(
            parallelism,
            worker_factory=DirectHttpWorker,
            operation_gate=operation_gate,
        )
        try:
            # Share the control-plane cancellation token without letting the execution plane
            # own or read the IPC channel.
            def mirror_cancel() -> None:
                cancel_event.wait()
                if cancel_event.is_set():
                    scheduler.cancel()

            mirror = threading.Thread(target=mirror_cancel, name="DirectHttpCancelMirror", daemon=True)
            mirror.start()
            futures = [scheduler.submit(transfer) for transfer in transfers]
            completed = 0
            for future in as_completed(futures):
                result = future.result()
                completed += 1
                if on_staged is not None:
                    on_staged(self._encode_result(result))
            activity = scheduler.admission.snapshot()
            return DirectHttpExecutionOutcome(
                transfer_count=completed,
                configured_parallelism=parallelism,
                peak_network_active=activity.peak,
            )
        finally:
            scheduler.close()

    @staticmethod
    def _encode_result(result) -> dict[str, object]:
        return {
            "artifact_id": str(result.artifact_id),
            "staging_path": str(result.staging_path),
            "sidecar_path": str(result.sidecar_path),
            "size_bytes": result.size_bytes,
            "sha256": result.sha256.hex(),
            "resumed_from": result.resumed_from,
            "attempts": result.attempts,
            "effective_url_host": result.effective_url_host,
            "etag": result.etag,
            "last_modified": result.last_modified,
        }

    @staticmethod
    def _decode_transfer(obj: Any) -> DirectHttpTransfer:
        if not isinstance(obj, dict):
            raise ValueError("transfer entry must be an object")
        url = str(obj["url"])
        source_fingerprint = str(
            obj.get("source_fingerprint") or hashlib.sha256(url.encode("utf-8")).hexdigest()
        )
        expected_sha_raw = obj.get("expected_sha256")
        expected_sha = None if expected_sha_raw in (None, "") else bytes.fromhex(str(expected_sha_raw))
        headers = obj.get("headers") or {}
        if not isinstance(headers, dict):
            raise ValueError("transfer headers must be an object")
        return DirectHttpTransfer(
            artifact_id=ArtifactId.parse(str(obj["artifact_id"])),
            generation=int(obj.get("generation") or 0),
            url=url,
            staging_path=Path(str(obj["staging_path"])),
            sidecar_path=Path(str(obj["sidecar_path"])),
            source_fingerprint=source_fingerprint,
            headers={str(k): str(v) for k, v in headers.items()},
            expected_size=(None if obj.get("expected_size") is None else int(obj["expected_size"])),
            expected_sha256=expected_sha,
            timeout_s=float(obj.get("timeout_s") or 30.0),
            redirect_policy=str(obj.get("redirect_policy") or "HTTP_OR_HTTPS"),
            network_scope_policy=str(obj.get("network_scope_policy") or "ANY"),
            network_scope_root=(None if obj.get("network_scope_root") in (None, "") else str(obj["network_scope_root"])),
            retry_policy=RetryPolicy(
                hard_ceiling=int(obj.get("retry_ceiling") or 0),
                base_delay_s=float(obj.get("retry_base_delay_s") or 0.25),
                max_delay_s=float(obj.get("retry_max_delay_s") or 8.0),
                jitter_s=float(obj.get("retry_jitter_s") or 0.25),
            ),
            checkpoint_bytes=int(obj.get("checkpoint_bytes") or 4 * 1024 * 1024),
            checkpoint_interval_s=float(obj.get("checkpoint_interval_s") or 2.0),
        )
