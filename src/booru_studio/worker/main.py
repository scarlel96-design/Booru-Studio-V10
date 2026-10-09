from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
from pathlib import Path

from booru_studio.common.ids import ArtifactId, CommitIntentId, PathClaimId
from booru_studio.common.paths import reject_symlink
from booru_studio.domain.file_commit import CommitGrant, FileCommitStrategy
from booru_studio.ipc.auth import core_proof, derive_session_keys, verify, worker_proof
from booru_studio.ipc.core_worker_protocol import CoreWorkerMessage, make_envelope, validate_envelope
from booru_studio.ipc.stream_connection import EnvelopeConnection, StreamEnvelopeConnection
from booru_studio.worker.bootstrap import WorkerBootstrap, read_bootstrap_fd, read_bootstrap_handle
from booru_studio.worker.execution_plane import DirectHttpExecutionOutcome, DirectHttpExecutionPlane
from booru_studio.worker.staging import perform_commit


def _authenticate(connection: EnvelopeConnection, packet: WorkerBootstrap) -> None:
    hello = connection.recv()
    if validate_envelope(hello) is not CoreWorkerMessage.CORE_HELLO:
        raise PermissionError("expected CORE_HELLO")
    if str(hello.payload["core_instance_id"]) != str(packet.core_instance_id):
        raise PermissionError("Core identity mismatch")
    core_nonce = bytes.fromhex(str(hello.payload["core_nonce"]))
    if len(core_nonce) != 32:
        raise PermissionError("invalid Core nonce")
    worker_nonce = os.urandom(32)
    connection.send(make_envelope(
        CoreWorkerMessage.WORKER_CHALLENGE,
        message_id="auth-worker-challenge",
        payload={
            "worker_session_id": str(packet.worker_session_id),
            "worker_nonce": worker_nonce.hex(),
            "proof": worker_proof(packet, core_nonce, worker_nonce).hex(),
        },
    ))
    proof = connection.recv()
    if validate_envelope(proof) is not CoreWorkerMessage.CORE_PROOF:
        raise PermissionError("expected CORE_PROOF")
    verify(core_proof(packet, core_nonce, worker_nonce), str(proof.payload["proof"]))
    derive_session_keys(packet, core_nonce, worker_nonce)  # reserved for later AEAD credential payloads
    connection.send(make_envelope(
        CoreWorkerMessage.AUTH_OK,
        message_id="auth-ok",
        payload={"worker_session_id": str(packet.worker_session_id)},
    ))


class _CoreLeaseState:
    """Worker-local admission fence driven only by authenticated Core control messages."""

    def __init__(self, start_payload: dict[str, object]) -> None:
        self.operation_gate = threading.Event()
        self.operation_gate.set()  # legacy/source START_RUN without a lease remains compatible
        self._lock = threading.Lock()
        self._enabled = False
        self._epoch = 0
        self._deadline = 0.0
        epoch = start_payload.get("core_lease_epoch")
        valid = start_payload.get("core_lease_valid_for_ms")
        if epoch is not None and valid is not None:
            self._enabled = True
            self._accept(int(epoch), int(valid))

    def _accept(self, epoch: int, valid_for_ms: int) -> None:
        if epoch <= 0 or not 1000 <= valid_for_ms <= 60_000:
            raise ValueError("invalid Core lease")
        with self._lock:
            if epoch <= self._epoch:
                raise ValueError("stale Core lease epoch")
            self._epoch = epoch
            self._deadline = time.monotonic() + valid_for_ms / 1000.0
            self.operation_gate.set()

    def accept_envelope(self, envelope, packet: WorkerBootstrap) -> None:
        if validate_envelope(envelope) is not CoreWorkerMessage.CORE_LEASE:
            raise ValueError("expected CORE_LEASE")
        if str(envelope.payload["run_id"]) != str(packet.run_id):
            raise PermissionError("Core lease Run identity mismatch")
        self._enabled = True
        self._accept(int(envelope.payload["core_lease_epoch"]), int(envelope.payload["valid_for_ms"]))

    def expire_if_needed(self) -> None:
        with self._lock:
            if self._enabled and time.monotonic() >= self._deadline:
                self.operation_gate.clear()


def _send_worker_tx(
    connection: EnvelopeConnection,
    *,
    tx_seq: int,
    tx_type: str,
    tx_payload: dict[str, object],
    packet: WorkerBootstrap | None = None,
    lease_state: _CoreLeaseState | None = None,
    control_handler=None,
) -> None:
    connection.send(make_envelope(
        CoreWorkerMessage.WORKER_TX,
        message_id=f"tx-{tx_seq}",
        payload={"tx_seq": tx_seq, "tx_type": tx_type, "tx_payload": tx_payload},
    ))
    while True:
        incoming = connection.recv()
        message = validate_envelope(incoming)
        if message is CoreWorkerMessage.CORE_LEASE and lease_state is not None and packet is not None:
            lease_state.accept_envelope(incoming, packet)
            continue
        if message in {CoreWorkerMessage.PAUSE_RUN, CoreWorkerMessage.CANCEL_RUN} and control_handler is not None:
            control_handler(incoming)
            continue
        if message is CoreWorkerMessage.WORKER_TX_ACK:
            if int(incoming.payload["last_contiguous_tx_seq"]) < tx_seq:
                raise ValueError("invalid Worker tx ACK")
            return
        raise ValueError(f"unexpected message while awaiting Worker tx ACK: {message.value}")


def _decode_commit_grant(payload: dict[str, object]) -> CommitGrant:
    digest = bytes.fromhex(str(payload["expected_sha256"]))
    if len(digest) != 32:
        raise ValueError("invalid commit SHA-256")
    return CommitGrant(
        commit_intent_id=CommitIntentId.parse(str(payload["commit_intent_id"])),
        artifact_id=ArtifactId.parse(str(payload["artifact_id"])),
        path_claim_id=PathClaimId.parse(str(payload["path_claim_id"])),
        strategy=FileCommitStrategy(str(payload["strategy"])),
        staging_path=Path(str(payload["staging_path"])),
        final_path=Path(str(payload["final_path"])),
        expected_size=int(payload["expected_size"]),
        expected_sha256=digest,
        marker_path=Path(str(payload["marker_path"])),
    )


def _run_direct_http(
    connection: EnvelopeConnection,
    packet: WorkerBootstrap,
    execution_plan: dict[str, object],
    lease_state: _CoreLeaseState,
) -> int:
    cancel_event = threading.Event()
    done = threading.Event()
    staged_queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=128)
    result_box: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

    def execute() -> None:
        try:
            outcome = DirectHttpExecutionPlane().run(
                execution_plan, cancel_event=cancel_event, on_staged=staged_queue.put,
                operation_gate=lease_state.operation_gate,
            )
        except BaseException as exc:
            result_box.put(("error", exc))
        else:
            result_box.put(("ok", outcome))
        finally:
            done.set()

    thread = threading.Thread(target=execute, name="WorkerExecutionPlane", daemon=False)
    thread.start()
    lease_monitor_stop = threading.Event()
    def monitor_lease() -> None:
        while not lease_monitor_stop.wait(0.1):
            lease_state.expire_if_needed()
    lease_monitor = threading.Thread(target=monitor_lease, name="CoreLeaseFence", daemon=True)
    lease_monitor.start()
    cancelled = False
    paused = False
    tx_seq = 2
    committed = 0

    def handle_control(incoming) -> None:
        nonlocal cancelled, paused
        message = validate_envelope(incoming)
        if message is CoreWorkerMessage.PAUSE_RUN:
            if str(incoming.payload["run_id"]) != str(packet.run_id):
                raise PermissionError("Pause run identity mismatch")
            cancel_event.set()
            paused = True
            connection.send(make_envelope(
                CoreWorkerMessage.PAUSE_ACK,
                message_id="pause-ack",
                payload={"run_id": str(packet.run_id)},
            ))
            return
        if message is not CoreWorkerMessage.CANCEL_RUN:
            raise ValueError(f"unexpected control message during execution: {message.value}")
        if str(incoming.payload["run_id"]) != str(packet.run_id):
            raise PermissionError("Cancel run identity mismatch")
        cancel_event.set()
        cancelled = True
        paused = False  # Cancel supersedes an earlier pause request before final observation.
        connection.send(make_envelope(
            CoreWorkerMessage.CANCEL_ACK,
            message_id="cancel-ack",
            payload={"run_id": str(packet.run_id)},
        ))

    def poll_control(timeout_s: float) -> bool:
        try:
            incoming = connection.recv_timeout(timeout_s)
        except TimeoutError:
            return False
        message = validate_envelope(incoming)
        if message is CoreWorkerMessage.CORE_LEASE:
            lease_state.accept_envelope(incoming, packet)
            return True
        if message in {CoreWorkerMessage.PAUSE_RUN, CoreWorkerMessage.CANCEL_RUN}:
            handle_control(incoming)
            return True
        raise ValueError(f"unexpected control message during execution: {message.value}")

    def commit_staged(result: dict[str, object]) -> None:
        nonlocal tx_seq, committed
        _send_worker_tx(
            connection,
            tx_seq=tx_seq,
            tx_type="TRANSFER_STAGED",
            tx_payload=dict(result),
            packet=packet, lease_state=lease_state, control_handler=handle_control,
        )
        tx_seq += 1
        if cancelled or paused:
            return
        while True:
            grant_envelope = connection.recv()
            grant_message = validate_envelope(grant_envelope)
            if grant_message is CoreWorkerMessage.CORE_LEASE:
                lease_state.accept_envelope(grant_envelope, packet)
                continue
            if grant_message in {CoreWorkerMessage.PAUSE_RUN, CoreWorkerMessage.CANCEL_RUN}:
                handle_control(grant_envelope)
                return
            if grant_message is not CoreWorkerMessage.FILE_COMMIT_GRANT:
                raise ValueError("expected FILE_COMMIT_GRANT")
            break
        grant = _decode_commit_grant(dict(grant_envelope.payload))
        if str(grant.artifact_id) != str(result["artifact_id"]):
            raise PermissionError("commit grant artifact mismatch")
        commit_result = perform_commit(grant)
        connection.send(make_envelope(
            CoreWorkerMessage.FILE_COMMIT_RESULT,
            message_id=f"commit-result-{grant.commit_intent_id}",
            payload={
                "commit_intent_id": str(commit_result.commit_intent_id),
                "size_bytes": commit_result.size_bytes,
                "sha256": commit_result.sha256.hex(),
                "marker_written": commit_result.marker_written,
            },
        ))
        while True:
            commit_ack = connection.recv()
            commit_message = validate_envelope(commit_ack)
            if commit_message is CoreWorkerMessage.CORE_LEASE:
                lease_state.accept_envelope(commit_ack, packet)
                continue
            if commit_message is not CoreWorkerMessage.FILE_COMMIT_ACK:
                raise ValueError("expected FILE_COMMIT_ACK")
            break
        if str(commit_ack.payload["commit_intent_id"]) != str(grant.commit_intent_id):
            raise ValueError("commit ACK intent mismatch")
        sidecar_path = Path(str(result["sidecar_path"]))
        reject_symlink(sidecar_path)
        sidecar_path.unlink(missing_ok=True)
        committed += 1

    # Keep IPC/control ownership on this thread while the blocking network engine runs elsewhere.
    while not done.is_set() or not staged_queue.empty():
        # Control-plane messages get priority over starting another irreversible FileCommit.
        poll_control(0.0)
        if cancelled or paused:
            # Results completed before Pause/Cancel but not across FILE_COMMIT_GRANTED remain
            # resumable staging; they are deliberately not promoted after the durable intent.
            while not staged_queue.empty():
                try:
                    staged_queue.get_nowait()
                except queue.Empty:
                    break
            if not done.is_set():
                poll_control(0.05)
            continue
        try:
            staged = staged_queue.get_nowait()
        except queue.Empty:
            poll_control(0.05)
            continue
        commit_staged(staged)

    thread.join()
    lease_monitor_stop.set()
    lease_monitor.join(timeout=1.0)
    status, payload = result_box.get_nowait()

    if paused:
        _send_worker_tx(
            connection,
            tx_seq=tx_seq,
            tx_type="PAUSE_OBSERVED",
            tx_payload={"run_id": str(packet.run_id)},
            packet=packet, lease_state=lease_state, control_handler=handle_control,
        )
        connection.send(make_envelope(
            CoreWorkerMessage.GOODBYE,
            message_id="goodbye-paused",
            payload={"reason": "paused"},
        ))
        return 0

    if cancelled:
        _send_worker_tx(
            connection,
            tx_seq=tx_seq,
            tx_type="CANCEL_OBSERVED",
            tx_payload={"run_id": str(packet.run_id)},
            packet=packet, lease_state=lease_state, control_handler=handle_control,
        )
        connection.send(make_envelope(
            CoreWorkerMessage.GOODBYE,
            message_id="goodbye-cancelled",
            payload={"reason": "cancelled"},
        ))
        return 0

    if status == "error":
        exc = payload
        _send_worker_tx(
            connection,
            tx_seq=tx_seq,
            tx_type="RUN_EXECUTION_FAILED",
            tx_payload={"run_id": str(packet.run_id), "error_type": type(exc).__name__},
            packet=packet, lease_state=lease_state, control_handler=handle_control,
        )
        connection.send(make_envelope(
            CoreWorkerMessage.ERROR,
            message_id="execution-error",
            payload={"code": "ENGINE_EXECUTION_FAILED"},
        ))
        return 2

    outcome = payload
    if not isinstance(outcome, DirectHttpExecutionOutcome):
        raise RuntimeError("execution plane returned invalid result")
    _send_worker_tx(
        connection,
        tx_seq=tx_seq,
        tx_type="RUN_TRANSFER_SUMMARY",
        tx_payload={
            "run_id": str(packet.run_id),
            "committed": committed,
            "transfer_count": outcome.transfer_count,
            "configured_parallelism": outcome.configured_parallelism,
            "peak_network_active": outcome.peak_network_active,
        },
        packet=packet, lease_state=lease_state,
    )
    connection.send(make_envelope(
        CoreWorkerMessage.GOODBYE,
        message_id="goodbye-complete",
        payload={"reason": "completed"},
    ))
    return 0


def run_worker(connection: EnvelopeConnection, packet: WorkerBootstrap) -> int:
    _authenticate(connection, packet)
    start = connection.recv()
    if validate_envelope(start) is not CoreWorkerMessage.START_RUN:
        raise ValueError("expected START_RUN")
    if str(start.payload["run_id"]) != str(packet.run_id):
        raise PermissionError("Run identity mismatch")
    if str(start.payload["job_id"]) != str(packet.job_id):
        raise PermissionError("Job identity mismatch")
    if int(start.payload["worker_generation"]) != packet.worker_generation:
        raise PermissionError("Worker generation mismatch")
    lease_state = _CoreLeaseState(dict(start.payload))
    _send_worker_tx(
        connection,
        tx_seq=1,
        tx_type="RUN_STARTED_OBSERVED",
        tx_payload={"run_id": str(packet.run_id)},
        packet=packet, lease_state=lease_state,
    )

    execution_plan = start.payload.get("execution_plan")
    if isinstance(execution_plan, dict):
        return _run_direct_http(connection, packet, dict(execution_plan), lease_state)

    # Compatibility path retained for the sealed Sprint 3 control harness.
    command = connection.recv()
    message = validate_envelope(command)
    if message not in {CoreWorkerMessage.CANCEL_RUN, CoreWorkerMessage.PAUSE_RUN}:
        raise ValueError("compatibility harness expects CANCEL_RUN or PAUSE_RUN after START_RUN")
    if str(command.payload["run_id"]) != str(packet.run_id):
        raise PermissionError("control Run identity mismatch")
    paused = message is CoreWorkerMessage.PAUSE_RUN
    connection.send(make_envelope(
        CoreWorkerMessage.PAUSE_ACK if paused else CoreWorkerMessage.CANCEL_ACK,
        message_id="pause-ack" if paused else "cancel-ack",
        payload={"run_id": str(packet.run_id)},
    ))
    _send_worker_tx(
        connection,
        tx_seq=2,
        tx_type="PAUSE_OBSERVED" if paused else "CANCEL_OBSERVED",
        tx_payload={"run_id": str(packet.run_id)},
    )
    connection.send(make_envelope(
        CoreWorkerMessage.GOODBYE,
        message_id="goodbye",
        payload={"reason": "paused" if paused else "cancelled"},
    ))
    return 0


def _run_qlocal(packet: WorkerBootstrap) -> int:
    # Lazy import keeps the source repository testable without PySide6.
    from booru_studio.ipc.qlocal import connect_local_socket
    from booru_studio.ipc.qt_connection import QtLocalEnvelopeConnection
    socket = connect_local_socket(packet.endpoint_name)
    return run_worker(QtLocalEnvelopeConnection(socket), packet)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    bootstrap = parser.add_mutually_exclusive_group(required=True)
    bootstrap.add_argument("--worker-bootstrap-fd", type=int)
    bootstrap.add_argument("--worker-bootstrap-handle", type=int)
    parser.add_argument("--source-stdio-harness", action="store_true")
    args = parser.parse_args(argv)
    packet = (
        read_bootstrap_handle(args.worker_bootstrap_handle)
        if args.worker_bootstrap_handle is not None
        else read_bootstrap_fd(args.worker_bootstrap_fd)
    )
    if args.source_stdio_harness:
        connection = StreamEnvelopeConnection(sys.stdin.buffer, sys.stdout.buffer)
        return run_worker(connection, packet)
    return _run_qlocal(packet)


if __name__ == "__main__":
    raise SystemExit(main())
