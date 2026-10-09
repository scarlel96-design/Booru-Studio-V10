from __future__ import annotations

import os
from dataclasses import replace

import pytest

from booru_studio.common.ids import CoreInstanceId, EnginePackId, JobId, JobRunId, WorkerSessionId
from booru_studio.common.paths import normalize_relative_path
from booru_studio.ipc.auth import worker_proof
from booru_studio.ipc.core_worker_protocol import CoreWorkerMessage, envelope_from_dict, envelope_to_dict, make_envelope
from booru_studio.worker.bootstrap import WorkerBootstrap


@pytest.mark.parametrize("raw", [
    "file.bin",
    "한글/이미지.jpg",
    "새 폴더 (6)/video.mp4",
    "日本語/写真.webp",
    "accentué/résumé.txt",
    "emoji/사진😀.png",
    "a.b.c/file.tar",
    "space folder/file name.mkv",
])
def test_path_matrix_accepts_safe_unicode_and_windows_compatible_names(raw: str) -> None:
    assert normalize_relative_path(raw)


@pytest.mark.parametrize("raw", [
    "../escape",
    "../../x",
    "/rooted",
    "C:/drive",
    "NUL.txt",
    "COM9.bin",
    "bad|name",
    "folder/trailing.",
])
def test_path_matrix_rejects_unsafe_windows_targets(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_relative_path(raw)


@pytest.mark.parametrize("message,payload", [
    (CoreWorkerMessage.CORE_HELLO, {"core_instance_id": "c", "core_nonce": "00"}),
    (CoreWorkerMessage.WORKER_CHALLENGE, {"worker_session_id": "w", "worker_nonce": "00", "proof": "00"}),
    (CoreWorkerMessage.CORE_PROOF, {"proof": "00"}),
    (CoreWorkerMessage.AUTH_OK, {"worker_session_id": "w"}),
    (CoreWorkerMessage.START_RUN, {"run_id": "r", "job_id": "j", "worker_generation": 0}),
    (CoreWorkerMessage.WORKER_TX_ACK, {"last_contiguous_tx_seq": 0}),
    (CoreWorkerMessage.CANCEL_RUN, {"run_id": "r"}),
    (CoreWorkerMessage.GOODBYE, {"reason": "done"}),
])
def test_core_worker_message_matrix_roundtrips(message: CoreWorkerMessage, payload: dict[str, object]) -> None:
    env = make_envelope(message, message_id="matrix", payload=payload)
    parsed = envelope_from_dict(envelope_to_dict(env))
    assert parsed.message_type == message.value


def _packet() -> WorkerBootstrap:
    return WorkerBootstrap(
        core_instance_id=CoreInstanceId.new(), worker_session_id=WorkerSessionId.new(),
        run_id=JobRunId.new(), job_id=JobId.new(), engine_pack_id=EnginePackId.new(),
        worker_generation=1, expected_pid=max(os.getpid(), 1), endpoint_name="ep-a",
        secret=b"S" * 32, core_capabilities=("core-a",), worker_capabilities=("worker-a",),
    )


@pytest.mark.parametrize("field", [
    "job_id",
    "run_id",
    "engine_pack_id",
    "worker_generation",
    "expected_pid",
    "endpoint_name",
    "core_capabilities",
    "worker_capabilities",
])
def test_authentication_transcript_binds_runtime_identity(field: str) -> None:
    packet = _packet()
    core_nonce = b"C" * 32
    worker_nonce = b"W" * 32
    baseline = worker_proof(packet, core_nonce, worker_nonce)
    changes = {
        "job_id": JobId.new(),
        "run_id": JobRunId.new(),
        "engine_pack_id": EnginePackId.new(),
        "worker_generation": 2,
        "expected_pid": packet.expected_pid + 1,
        "endpoint_name": "ep-b",
        "core_capabilities": ("core-b",),
        "worker_capabilities": ("worker-b",),
    }
    changed = replace(packet, **{field: changes[field]})
    assert worker_proof(changed, core_nonce, worker_nonce) != baseline
