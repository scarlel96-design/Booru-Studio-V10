from __future__ import annotations

import os
import socket
import threading

import pytest

from booru_studio.common.ids import CoreInstanceId, EnginePackId, JobId, JobRunId, WorkerSessionId
from booru_studio.ipc.auth import core_proof, derive_session_keys, verify, worker_proof
from booru_studio.ipc.core_worker_protocol import CoreWorkerMessage, envelope_from_dict, envelope_to_dict, make_envelope
from booru_studio.ipc.stream_connection import StreamEnvelopeConnection
from booru_studio.worker.bootstrap import WorkerBootstrap, decode_bootstrap, encode_bootstrap


def _packet(secret: bytes | None = None, expected_pid: int | None = None) -> WorkerBootstrap:
    return WorkerBootstrap(
        core_instance_id=CoreInstanceId.new(), worker_session_id=WorkerSessionId.new(),
        run_id=JobRunId.new(), job_id=JobId.new(), engine_pack_id=EnginePackId.new(),
        worker_generation=3, expected_pid=expected_pid or os.getpid(), endpoint_name="ep-test",
        secret=secret or os.urandom(32), core_capabilities=("a",), worker_capabilities=("b",),
    )


def test_bootstrap_roundtrip() -> None:
    packet = _packet()
    decoded = decode_bootstrap(encode_bootstrap(packet))
    assert decoded == packet
    # read_bootstrap_fd additionally fences the packet to the actual Worker PID.
    import os as _os
    from booru_studio.worker.bootstrap import read_bootstrap_fd
    r, w = _os.pipe()
    try:
        _os.write(w, encode_bootstrap(_packet(expected_pid=_os.getpid() + 100000)))
        _os.close(w); w = -1
        with pytest.raises(PermissionError):
            read_bootstrap_fd(r)
    finally:
        if w >= 0: _os.close(w)
        _os.close(r)


def test_bootstrap_requires_32_byte_secret() -> None:
    with pytest.raises(ValueError): _packet(b"short")


def test_directional_session_keys_are_distinct_and_deterministic() -> None:
    packet = _packet(); c = b"c" * 32; w = b"w" * 32
    first = derive_session_keys(packet, c, w); second = derive_session_keys(packet, c, w)
    assert first == second
    assert first.core_to_worker != first.worker_to_core
    assert len(first.core_to_worker) == len(first.worker_to_core) == 32


def test_auth_proofs_bind_nonce_and_identity() -> None:
    packet = _packet(); c = b"c" * 32; w = b"w" * 32
    wp = worker_proof(packet, c, w); cp = core_proof(packet, c, w)
    assert wp != cp
    verify(wp, wp.hex())
    with pytest.raises(PermissionError): verify(wp, worker_proof(packet, b"x" * 32, w).hex())


def test_core_worker_envelope_roundtrip_and_plane_validation() -> None:
    env = make_envelope(CoreWorkerMessage.CANCEL_RUN, message_id="m", payload={"run_id": str(JobRunId.new())})
    parsed = envelope_from_dict(envelope_to_dict(env))
    assert parsed.message_type == CoreWorkerMessage.CANCEL_RUN.value
    bad = envelope_to_dict(env); bad["plane"] = "TRANSACTION"
    with pytest.raises(ValueError): envelope_from_dict(bad)


def test_stream_connection_over_socketpair() -> None:
    a, b = socket.socketpair()
    try:
        ar = a.makefile("rb", buffering=0); aw = a.makefile("wb", buffering=0)
        br = b.makefile("rb", buffering=0); bw = b.makefile("wb", buffering=0)
        ca = StreamEnvelopeConnection(ar, aw); cb = StreamEnvelopeConnection(br, bw)
        env = make_envelope(CoreWorkerMessage.CANCEL_RUN, message_id="m", payload={"run_id": str(JobRunId.new())})
        ca.send(env); got = cb.recv()
        assert got.message_type == env.message_type and dict(got.payload) == dict(env.payload)
    finally:
        a.close(); b.close()
