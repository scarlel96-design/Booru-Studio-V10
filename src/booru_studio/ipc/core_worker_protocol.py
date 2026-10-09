from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from booru_studio.ipc.envelopes import (
    Envelope, MessagePlane, ProtocolFamily, ProtocolVersion,
    envelope_from_wire_dict, envelope_to_wire_dict,
)

CORE_WORKER_VERSION = ProtocolVersion(1, 1)


class CoreWorkerMessage(StrEnum):
    CORE_HELLO = "CORE_HELLO"
    WORKER_CHALLENGE = "WORKER_CHALLENGE"
    CORE_PROOF = "CORE_PROOF"
    AUTH_OK = "AUTH_OK"
    START_RUN = "START_RUN"
    CORE_LEASE = "CORE_LEASE"
    WORKER_TX = "WORKER_TX"
    WORKER_TX_ACK = "WORKER_TX_ACK"
    FILE_COMMIT_GRANT = "FILE_COMMIT_GRANT"
    FILE_COMMIT_RESULT = "FILE_COMMIT_RESULT"
    FILE_COMMIT_ACK = "FILE_COMMIT_ACK"
    PAUSE_RUN = "PAUSE_RUN"
    PAUSE_ACK = "PAUSE_ACK"
    CANCEL_RUN = "CANCEL_RUN"
    CANCEL_ACK = "CANCEL_ACK"
    GOODBYE = "GOODBYE"
    ERROR = "ERROR"


_ALLOWED_PLANE: dict[CoreWorkerMessage, MessagePlane] = {
    CoreWorkerMessage.CORE_HELLO: MessagePlane.CONTROL,
    CoreWorkerMessage.WORKER_CHALLENGE: MessagePlane.CONTROL,
    CoreWorkerMessage.CORE_PROOF: MessagePlane.CONTROL,
    CoreWorkerMessage.AUTH_OK: MessagePlane.CONTROL,
    CoreWorkerMessage.START_RUN: MessagePlane.CONTROL,
    CoreWorkerMessage.CORE_LEASE: MessagePlane.CONTROL,
    CoreWorkerMessage.WORKER_TX: MessagePlane.TRANSACTION,
    CoreWorkerMessage.WORKER_TX_ACK: MessagePlane.TRANSACTION,
    CoreWorkerMessage.FILE_COMMIT_GRANT: MessagePlane.TRANSACTION,
    CoreWorkerMessage.FILE_COMMIT_RESULT: MessagePlane.TRANSACTION,
    CoreWorkerMessage.FILE_COMMIT_ACK: MessagePlane.TRANSACTION,
    CoreWorkerMessage.PAUSE_RUN: MessagePlane.CONTROL,
    CoreWorkerMessage.PAUSE_ACK: MessagePlane.CONTROL,
    CoreWorkerMessage.CANCEL_RUN: MessagePlane.CONTROL,
    CoreWorkerMessage.CANCEL_ACK: MessagePlane.CONTROL,
    CoreWorkerMessage.GOODBYE: MessagePlane.CONTROL,
    CoreWorkerMessage.ERROR: MessagePlane.CONTROL,
}


def make_envelope(message: CoreWorkerMessage, *, message_id: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        family=ProtocolFamily.CORE_WORKER,
        version=CORE_WORKER_VERSION,
        plane=_ALLOWED_PLANE[message],
        message_type=message.value,
        message_id=message_id,
        trace_id=None,
        payload=payload,
    )


def envelope_to_dict(envelope: Envelope) -> dict[str, Any]:
    return envelope_to_wire_dict(envelope)


def envelope_from_dict(obj: dict[str, Any]) -> Envelope:
    envelope = envelope_from_wire_dict(obj)
    validate_envelope(envelope)
    return envelope


def validate_envelope(envelope: Envelope) -> CoreWorkerMessage:
    if envelope.family is not ProtocolFamily.CORE_WORKER:
        raise ValueError("wrong protocol family")
    if envelope.version.major != CORE_WORKER_VERSION.major:
        raise ValueError("incompatible protocol major")
    try:
        message = CoreWorkerMessage(envelope.message_type)
    except ValueError as exc:
        raise ValueError("unknown Core↔Worker message") from exc
    if envelope.plane is not _ALLOWED_PLANE[message]:
        raise ValueError("message sent on invalid plane")
    _validate_payload(message, dict(envelope.payload))
    return message


def _require(payload: dict[str, object], key: str, typ: type) -> object:
    if key not in payload or not isinstance(payload[key], typ):
        raise ValueError(f"invalid or missing payload field: {key}")
    return payload[key]


def _validate_payload(message: CoreWorkerMessage, payload: dict[str, object]) -> None:
    if message is CoreWorkerMessage.CORE_HELLO:
        _require(payload, "core_instance_id", str); _require(payload, "core_nonce", str)
    elif message is CoreWorkerMessage.WORKER_CHALLENGE:
        _require(payload, "worker_session_id", str); _require(payload, "worker_nonce", str); _require(payload, "proof", str)
    elif message is CoreWorkerMessage.CORE_PROOF:
        _require(payload, "proof", str)
    elif message is CoreWorkerMessage.AUTH_OK:
        _require(payload, "worker_session_id", str)
    elif message is CoreWorkerMessage.START_RUN:
        _require(payload, "run_id", str); _require(payload, "job_id", str); _require(payload, "worker_generation", int)
        if "execution_plan" in payload and not isinstance(payload["execution_plan"], dict):
            raise ValueError("execution_plan must be object")
        lease_epoch = payload.get("core_lease_epoch")
        lease_valid = payload.get("core_lease_valid_for_ms")
        if (lease_epoch is None) != (lease_valid is None):
            raise ValueError("START_RUN Core lease fields must appear together")
        if lease_epoch is not None:
            if not isinstance(lease_epoch, int) or lease_epoch <= 0:
                raise ValueError("core_lease_epoch must be positive")
            if not isinstance(lease_valid, int) or not 1000 <= lease_valid <= 60_000:
                raise ValueError("core_lease_valid_for_ms outside supported range")
    elif message is CoreWorkerMessage.CORE_LEASE:
        _require(payload, "run_id", str)
        epoch = int(_require(payload, "core_lease_epoch", int))
        valid = int(_require(payload, "valid_for_ms", int))
        if epoch <= 0:
            raise ValueError("core_lease_epoch must be positive")
        if not 1000 <= valid <= 60_000:
            raise ValueError("Core lease duration outside supported range")
    elif message is CoreWorkerMessage.WORKER_TX:
        seq = int(_require(payload, "tx_seq", int))
        if seq <= 0: raise ValueError("tx_seq must be positive")
        _require(payload, "tx_type", str); _require(payload, "tx_payload", dict)
    elif message is CoreWorkerMessage.WORKER_TX_ACK:
        seq = int(_require(payload, "last_contiguous_tx_seq", int))
        if seq < 0: raise ValueError("ACK sequence cannot be negative")
    elif message is CoreWorkerMessage.FILE_COMMIT_GRANT:
        _require(payload, "commit_intent_id", str); _require(payload, "artifact_id", str)
        _require(payload, "path_claim_id", str); _require(payload, "strategy", str)
        _require(payload, "staging_path", str); _require(payload, "final_path", str)
        size = int(_require(payload, "expected_size", int))
        if size < 0: raise ValueError("expected_size cannot be negative")
        _require(payload, "expected_sha256", str); _require(payload, "marker_path", str)
    elif message is CoreWorkerMessage.FILE_COMMIT_RESULT:
        _require(payload, "commit_intent_id", str)
        size = int(_require(payload, "size_bytes", int))
        if size < 0: raise ValueError("size_bytes cannot be negative")
        _require(payload, "sha256", str); _require(payload, "marker_written", bool)
    elif message is CoreWorkerMessage.FILE_COMMIT_ACK:
        _require(payload, "commit_intent_id", str); _require(payload, "file_record_id", str)
        revision = int(_require(payload, "committed_state_revision", int))
        if revision < 0: raise ValueError("committed_state_revision cannot be negative")
    elif message is CoreWorkerMessage.PAUSE_RUN:
        _require(payload, "run_id", str)
    elif message is CoreWorkerMessage.PAUSE_ACK:
        _require(payload, "run_id", str)
    elif message is CoreWorkerMessage.CANCEL_RUN:
        _require(payload, "run_id", str)
    elif message is CoreWorkerMessage.CANCEL_ACK:
        _require(payload, "run_id", str)
    elif message is CoreWorkerMessage.GOODBYE:
        _require(payload, "reason", str)
    elif message is CoreWorkerMessage.ERROR:
        _require(payload, "code", str)
