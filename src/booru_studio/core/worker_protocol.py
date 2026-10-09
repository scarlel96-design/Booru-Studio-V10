from __future__ import annotations

import os
import time
from dataclasses import dataclass

from booru_studio.common.clock import Clock
from booru_studio.common.ids import CommitIntentId, JobId, JobRunId, WorkerSessionId
from booru_studio.ipc.auth import core_proof, derive_session_keys, verify, worker_proof
from booru_studio.ipc.core_worker_protocol import CoreWorkerMessage, make_envelope, validate_envelope
from booru_studio.ipc.stream_connection import EnvelopeConnection
from booru_studio.persistence.db_actor import DbActor
from booru_studio.persistence.repositories.job_repository import get_job
from booru_studio.persistence.repositories.worker_repository import get_worker_session, set_worker_session_state
from booru_studio.persistence.transactions.base import write_transaction
from booru_studio.persistence.transactions.job_transactions import apply_worker_control_observation
from booru_studio.persistence.transactions.worker_transactions import commit_worker_transaction
from booru_studio.worker.bootstrap import WorkerBootstrap
from booru_studio.domain.enums import ControlIntent
from booru_studio.domain.file_commit import CommitResult, FinalizeResult


@dataclass(frozen=True, slots=True)
class AuthenticatedWorker:
    worker_session_id: WorkerSessionId
    core_to_worker_key: bytes
    worker_to_core_key: bytes


@dataclass(frozen=True, slots=True)
class DirectHttpRunOutcome:
    finalized: tuple[FinalizeResult, ...]
    summary: dict[str, object]
    terminal_reason: str = "completed"


class _CoreLeaseEmitter:
    """Single-threaded Core->Worker lease sender integrated with protocol receive waits."""

    def __init__(self, packet: WorkerBootstrap, *, valid_for_ms: int = 6000, interval_ms: int = 2000) -> None:
        if not 1000 <= interval_ms < valid_for_ms <= 60_000:
            raise ValueError("invalid Core Worker lease timing")
        self._packet = packet
        self.valid_for_ms = valid_for_ms
        self.interval_s = interval_ms / 1000.0
        self.epoch = 1
        self._next_send = time.monotonic() + self.interval_s

    def start_fields(self) -> dict[str, int]:
        return {"core_lease_epoch": self.epoch, "core_lease_valid_for_ms": self.valid_for_ms}

    def _send_next(self, connection: EnvelopeConnection) -> None:
        self.epoch += 1
        connection.send(make_envelope(
            CoreWorkerMessage.CORE_LEASE,
            message_id=f"core-lease-{self.epoch}",
            payload={
                "run_id": str(self._packet.run_id),
                "core_lease_epoch": self.epoch,
                "valid_for_ms": self.valid_for_ms,
            },
        ))
        self._next_send = time.monotonic() + self.interval_s

    def recv(self, connection: EnvelopeConnection, *, on_idle=None):
        while True:
            if on_idle is not None:
                on_idle()
            remaining = self._next_send - time.monotonic()
            if remaining <= 0:
                self._send_next(connection)
                continue
            try:
                return connection.recv_timeout(min(0.5, max(0.05, remaining)))
            except TimeoutError:
                if time.monotonic() >= self._next_send:
                    self._send_next(connection)


class _DurableControlForwarder:
    """Poll durable Job control intent and forward each stronger intent at most once."""

    def __init__(self, db_actor: DbActor, packet: WorkerBootstrap, *, poll_interval_s: float = 0.1) -> None:
        if poll_interval_s <= 0:
            raise ValueError("control poll interval must be positive")
        self._db = db_actor
        self._packet = packet
        self._poll_interval_s = poll_interval_s
        self._next_poll = 0.0
        self.sent_intent: ControlIntent | None = None

    def _read_intent(self) -> ControlIntent:
        job = self._db.submit(lambda c: get_job(c, self._packet.job_id)).result(timeout=5)
        if job is None:
            raise KeyError(f"job not found: {self._packet.job_id}")
        return job.control_intent

    def poll(self, connection: EnvelopeConnection, *, force: bool = False) -> ControlIntent | None:
        now = time.monotonic()
        if not force and now < self._next_poll:
            return self.sent_intent
        self._next_poll = now + self._poll_interval_s
        intent = self._read_intent()
        message: CoreWorkerMessage | None = None
        if intent is ControlIntent.CANCEL_REQUESTED and self.sent_intent is not ControlIntent.CANCEL_REQUESTED:
            message = CoreWorkerMessage.CANCEL_RUN
        elif intent is ControlIntent.PAUSE_REQUESTED and self.sent_intent is None:
            message = CoreWorkerMessage.PAUSE_RUN
        if message is None:
            return self.sent_intent
        connection.send(make_envelope(
            message,
            message_id=f"durable-{intent.value.lower()}-{self._packet.run_id}",
            payload={"run_id": str(self._packet.run_id)},
        ))
        self.sent_intent = intent
        return intent


class CoreWorkerController:
    def __init__(self, db_actor: DbActor, clock: Clock) -> None:
        self._db = db_actor
        self._clock = clock

    def authenticate(self, connection: EnvelopeConnection, packet: WorkerBootstrap) -> AuthenticatedWorker:
        core_nonce = os.urandom(32)
        connection.send(make_envelope(
            CoreWorkerMessage.CORE_HELLO,
            message_id="auth-core-hello",
            payload={"core_instance_id": str(packet.core_instance_id), "core_nonce": core_nonce.hex()},
        ))
        challenge = connection.recv()
        if validate_envelope(challenge) is not CoreWorkerMessage.WORKER_CHALLENGE:
            raise PermissionError("expected Worker challenge")
        if str(challenge.payload["worker_session_id"]) != str(packet.worker_session_id):
            raise PermissionError("Worker session identity mismatch")
        worker_nonce = bytes.fromhex(str(challenge.payload["worker_nonce"]))
        if len(worker_nonce) != 32:
            raise PermissionError("invalid Worker nonce")
        verify(worker_proof(packet, core_nonce, worker_nonce), str(challenge.payload["proof"]))
        connection.send(make_envelope(
            CoreWorkerMessage.CORE_PROOF,
            message_id="auth-core-proof",
            payload={"proof": core_proof(packet, core_nonce, worker_nonce).hex()},
        ))
        auth_ok = connection.recv()
        if validate_envelope(auth_ok) is not CoreWorkerMessage.AUTH_OK:
            raise PermissionError("expected AUTH_OK")
        if str(auth_ok.payload["worker_session_id"]) != str(packet.worker_session_id):
            raise PermissionError("AUTH_OK Worker session mismatch")
        keys = derive_session_keys(packet, core_nonce, worker_nonce)
        now = self._clock.utc_ms()
        self._db.submit(lambda c: self._set_state(c, packet.worker_session_id, "AUTHENTICATED", now)).result(timeout=5)
        return AuthenticatedWorker(packet.worker_session_id, keys.core_to_worker, keys.worker_to_core)

    @staticmethod
    def _set_state(connection, worker_session_id: WorkerSessionId, state: str, now: int) -> None:
        with write_transaction(connection):
            set_worker_session_state(
                connection, worker_session_id=worker_session_id, state=state, now_utc_ms=now
            )

    def start_run(self, connection: EnvelopeConnection, packet: WorkerBootstrap) -> int:
        connection.send(make_envelope(
            CoreWorkerMessage.START_RUN,
            message_id="start-run",
            payload={
                "run_id": str(packet.run_id),
                "job_id": str(packet.job_id),
                "worker_generation": packet.worker_generation,
            },
        ))
        return self.receive_and_commit_worker_tx(connection, packet.worker_session_id)

    def _commit_worker_tx_envelope(
        self, connection: EnvelopeConnection, worker_session_id: WorkerSessionId, envelope,
        *, apply_control_state: bool = False,
    ) -> tuple[int, str, dict[str, object]]:
        if validate_envelope(envelope) is not CoreWorkerMessage.WORKER_TX:
            raise ValueError("expected WORKER_TX")
        tx_seq = int(envelope.payload["tx_seq"])
        tx_type = str(envelope.payload["tx_type"])
        payload = dict(envelope.payload["tx_payload"])
        now = self._clock.utc_ms()
        def side_effect(connection_db):
            if tx_type == "RUN_STARTED_OBSERVED":
                set_worker_session_state(
                    connection_db, worker_session_id=worker_session_id, state="RUNNING", now_utc_ms=now
                )
                return
            if apply_control_state and tx_type in {"PAUSE_OBSERVED", "CANCEL_OBSERVED"}:
                session = get_worker_session(connection_db, worker_session_id)
                if session is None:
                    raise KeyError("worker session not found")
                run_id = JobRunId.parse(str(session["run_id"]))
                job_id = JobId.parse(str(session["job_id"]))
                if str(payload.get("run_id", "")) != str(run_id):
                    raise PermissionError("Worker control observation Run identity mismatch")
                apply_worker_control_observation(
                    connection_db, run_id=run_id, job_id=job_id, observation=tx_type,
                    now_utc_ms=now,
                )
        ack = self._db.submit(
            lambda c: commit_worker_transaction(
                c,
                worker_session_id=worker_session_id,
                tx_seq=tx_seq,
                tx_type=tx_type,
                payload=payload,
                now_utc_ms=now,
                side_effect=side_effect,
            )
        ).result(timeout=5)
        connection.send(make_envelope(
            CoreWorkerMessage.WORKER_TX_ACK,
            message_id=f"worker-tx-ack-{ack}",
            payload={"last_contiguous_tx_seq": ack},
        ))
        return ack, tx_type, payload

    def receive_and_commit_worker_tx(self, connection: EnvelopeConnection, worker_session_id: WorkerSessionId) -> int:
        envelope = connection.recv()
        ack, _tx_type, _payload = self._commit_worker_tx_envelope(connection, worker_session_id, envelope)
        return ack

    @staticmethod
    def _commit_grant_payload(grant) -> dict[str, object]:
        return {
            "commit_intent_id": str(grant.commit_intent_id),
            "artifact_id": str(grant.artifact_id),
            "path_claim_id": str(grant.path_claim_id),
            "strategy": grant.strategy.value,
            "staging_path": str(grant.staging_path),
            "final_path": str(grant.final_path),
            "expected_size": grant.expected_size,
            "expected_sha256": grant.expected_sha256.hex(),
            "marker_path": str(grant.marker_path),
        }

    def run_direct_http_plan(
        self,
        connection: EnvelopeConnection,
        packet: WorkerBootstrap,
        *,
        execution_plan: dict[str, object],
        artifact_service,
    ) -> DirectHttpRunOutcome:
        """Drive a DirectHTTP Worker while forwarding durable Job control intents.

        Pause/Cancel is authoritative only after the Worker reports an observed checkpoint through
        the durable Worker transaction lane. A pending control intent fences FILE_COMMIT_GRANT, so
        a staged result cannot cross the irreversible commit boundary after the Core has observed
        that request.
        """
        lease = _CoreLeaseEmitter(packet)
        connection.send(make_envelope(
            CoreWorkerMessage.START_RUN,
            message_id="start-run-direct-http",
            payload={
                "run_id": str(packet.run_id),
                "job_id": str(packet.job_id),
                "worker_generation": packet.worker_generation,
                "execution_plan": execution_plan,
                **lease.start_fields(),
            },
        ))
        first = lease.recv(connection)
        _ack, tx_type, _payload = self._commit_worker_tx_envelope(
            connection, packet.worker_session_id, first
        )
        if tx_type != "RUN_STARTED_OBSERVED":
            raise ValueError("Worker did not observe START_RUN")

        control = _DurableControlForwarder(self._db, packet)
        finalized: list[FinalizeResult] = []
        summary: dict[str, object] = {}
        observed_control: str | None = None

        def poll_durable_control() -> None:
            control.poll(connection)

        while True:
            envelope = lease.recv(connection, on_idle=poll_durable_control)
            message = validate_envelope(envelope)

            if message in {CoreWorkerMessage.PAUSE_ACK, CoreWorkerMessage.CANCEL_ACK}:
                if str(envelope.payload["run_id"]) != str(packet.run_id):
                    raise PermissionError("Worker control ACK Run identity mismatch")
                continue

            if message is CoreWorkerMessage.GOODBYE:
                reason = str(envelope.payload["reason"])
                if reason not in {"completed", "paused", "cancelled"}:
                    raise RuntimeError(f"Worker ended unexpectedly: {reason}")
                if reason in {"paused", "cancelled"} and observed_control is None:
                    raise RuntimeError("Worker exited for control without durable observation")
                now = self._clock.utc_ms()
                self._db.submit(
                    lambda c: self._set_state(c, packet.worker_session_id, "CLOSED", now)
                ).result(timeout=5)
                return DirectHttpRunOutcome(tuple(finalized), dict(summary), reason)

            if message is CoreWorkerMessage.ERROR:
                now = self._clock.utc_ms()
                self._db.submit(
                    lambda c: self._set_state(c, packet.worker_session_id, "FAILED", now)
                ).result(timeout=5)
                raise RuntimeError(f"Worker execution failed: {envelope.payload['code']}")

            if message is not CoreWorkerMessage.WORKER_TX:
                raise ValueError(f"unexpected Worker message: {message.value}")

            _ack, tx_type, payload = self._commit_worker_tx_envelope(
                connection, packet.worker_session_id, envelope, apply_control_state=True
            )
            if tx_type in {"PAUSE_OBSERVED", "CANCEL_OBSERVED"}:
                observed_control = tx_type
                continue
            if tx_type == "RUN_TRANSFER_SUMMARY":
                summary = dict(payload)
                continue
            if tx_type == "RUN_EXECUTION_FAILED":
                continue
            if tx_type != "TRANSFER_STAGED":
                raise ValueError(f"unexpected Worker transaction: {tx_type}")

            # Register the resumable checkpoint before deciding whether the staged bytes may cross
            # FILE_COMMIT_GRANTED. This keeps Pause resumable without persisting any source secret.
            sidecar_path = __import__("pathlib").Path(str(payload["sidecar_path"]))
            state = artifact_service.register_resume_sidecar(sidecar_path)
            if str(state.artifact_id) != str(payload["artifact_id"]):
                raise ValueError("staged Artifact identity does not match resume sidecar")

            if control.poll(connection, force=True) is not None:
                # Worker accepts PAUSE/CANCEL while waiting for FILE_COMMIT_GRANT and abandons this
                # promotion. The app-owned staging bytes remain recoverable/resumable.
                continue

            grant = artifact_service.prepare_commit(artifact_id=state.artifact_id)
            connection.send(make_envelope(
                CoreWorkerMessage.FILE_COMMIT_GRANT,
                message_id=f"commit-grant-{grant.commit_intent_id}",
                payload=self._commit_grant_payload(grant),
            ))
            # FILE_COMMIT_GRANT is the irreversible boundary. Do not inject control between the grant
            # and its result/ACK; the next checkpoint will observe any later durable request.
            result_envelope = lease.recv(connection)
            if validate_envelope(result_envelope) is not CoreWorkerMessage.FILE_COMMIT_RESULT:
                raise ValueError("expected FILE_COMMIT_RESULT")
            if str(result_envelope.payload["commit_intent_id"]) != str(grant.commit_intent_id):
                raise ValueError("commit result intent mismatch")
            digest = bytes.fromhex(str(result_envelope.payload["sha256"]))
            if len(digest) != 32:
                raise ValueError("invalid Worker commit digest")
            result = CommitResult(
                commit_intent_id=CommitIntentId.parse(str(result_envelope.payload["commit_intent_id"])),
                size_bytes=int(result_envelope.payload["size_bytes"]),
                sha256=digest,
                marker_written=bool(result_envelope.payload["marker_written"]),
            )
            final = artifact_service.finalize_commit(result)
            finalized.append(final)
            connection.send(make_envelope(
                CoreWorkerMessage.FILE_COMMIT_ACK,
                message_id=f"commit-ack-{grant.commit_intent_id}",
                payload={
                    "commit_intent_id": str(grant.commit_intent_id),
                    "file_record_id": str(final.file_record_id),
                    "committed_state_revision": final.committed_state_revision,
                },
            ))

    def cancel_run(self, connection: EnvelopeConnection, packet: WorkerBootstrap) -> int:
        connection.send(make_envelope(
            CoreWorkerMessage.CANCEL_RUN,
            message_id="cancel-run",
            payload={"run_id": str(packet.run_id)},
        ))
        ack = connection.recv()
        if validate_envelope(ack) is not CoreWorkerMessage.CANCEL_ACK:
            raise ValueError("expected CANCEL_ACK")
        if str(ack.payload["run_id"]) != str(packet.run_id):
            raise ValueError("Cancel ACK run mismatch")
        seq = self.receive_and_commit_worker_tx(connection, packet.worker_session_id)
        goodbye = connection.recv()
        if validate_envelope(goodbye) is not CoreWorkerMessage.GOODBYE:
            raise ValueError("expected GOODBYE")
        now = self._clock.utc_ms()
        self._db.submit(lambda c: self._set_state(c, packet.worker_session_id, "CLOSED", now)).result(timeout=5)
        return seq
