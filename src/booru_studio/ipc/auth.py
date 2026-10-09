from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

from booru_studio.common.serialization import canonical_json_dumps
from booru_studio.worker.bootstrap import WorkerBootstrap


@dataclass(frozen=True, slots=True)
class SessionKeys:
    core_to_worker: bytes
    worker_to_core: bytes


def _transcript(packet: WorkerBootstrap, core_nonce: bytes, worker_nonce: bytes) -> bytes:
    payload = {
        "core_instance_id": str(packet.core_instance_id),
        "worker_session_id": str(packet.worker_session_id),
        "run_id": str(packet.run_id),
        "job_id": str(packet.job_id),
        "engine_pack_id": str(packet.engine_pack_id),
        "generation": packet.worker_generation,
        "expected_pid": packet.expected_pid,
        "endpoint": packet.endpoint_name,
        "protocol_major": packet.protocol_major,
        "protocol_minor": packet.protocol_minor,
        "core_capabilities": list(packet.core_capabilities),
        "worker_capabilities": list(packet.worker_capabilities),
        "core_nonce": core_nonce.hex(),
        "worker_nonce": worker_nonce.hex(),
    }
    return canonical_json_dumps(payload).encode("utf-8")


def worker_proof(packet: WorkerBootstrap, core_nonce: bytes, worker_nonce: bytes) -> bytes:
    return hmac.new(packet.secret, b"worker-proof\x00" + _transcript(packet, core_nonce, worker_nonce), hashlib.sha256).digest()


def core_proof(packet: WorkerBootstrap, core_nonce: bytes, worker_nonce: bytes) -> bytes:
    return hmac.new(packet.secret, b"core-proof\x00" + _transcript(packet, core_nonce, worker_nonce), hashlib.sha256).digest()


def verify(expected: bytes, supplied_hex: str) -> None:
    try:
        supplied = bytes.fromhex(supplied_hex)
    except ValueError as exc:
        raise PermissionError("invalid authentication proof encoding") from exc
    if not hmac.compare_digest(expected, supplied):
        raise PermissionError("authentication proof mismatch")


def _hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def _hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    out = b""; previous = b""; counter = 1
    while len(out) < length:
        previous = hmac.new(prk, previous + info + bytes([counter]), hashlib.sha256).digest()
        out += previous; counter += 1
    return out[:length]


def derive_session_keys(packet: WorkerBootstrap, core_nonce: bytes, worker_nonce: bytes) -> SessionKeys:
    transcript_hash = hashlib.sha256(_transcript(packet, core_nonce, worker_nonce)).digest()
    prk = _hkdf_extract(transcript_hash, packet.secret)
    return SessionKeys(
        core_to_worker=_hkdf_expand(prk, b"booru-studio/core-to-worker", 32),
        worker_to_core=_hkdf_expand(prk, b"booru-studio/worker-to-core", 32),
    )
