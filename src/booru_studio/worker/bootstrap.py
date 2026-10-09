from __future__ import annotations

import base64
import json
import os
import struct
from dataclasses import dataclass

from booru_studio.common.ids import (
    CoreInstanceId,
    EnginePackId,
    JobId,
    JobRunId,
    WorkerSessionId,
)
from booru_studio.common.serialization import canonical_json_dumps, json_loads_object

_MAX_BOOTSTRAP = 64 * 1024
_HEADER = struct.Struct(">I")


@dataclass(frozen=True, slots=True)
class WorkerBootstrap:
    core_instance_id: CoreInstanceId
    worker_session_id: WorkerSessionId
    run_id: JobRunId
    job_id: JobId
    engine_pack_id: EnginePackId
    worker_generation: int
    expected_pid: int
    endpoint_name: str
    secret: bytes
    core_capabilities: tuple[str, ...] = ()
    worker_capabilities: tuple[str, ...] = ()
    protocol_major: int = 1
    protocol_minor: int = 0

    def __post_init__(self) -> None:
        if len(self.secret) != 32:
            raise ValueError("bootstrap secret must be exactly 32 bytes")
        if self.expected_pid <= 0 or self.worker_generation < 0:
            raise ValueError("invalid PID/generation")
        if not self.endpoint_name or len(self.endpoint_name) > 240:
            raise ValueError("invalid endpoint name")

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": 1,
            "core_instance_id": str(self.core_instance_id),
            "worker_session_id": str(self.worker_session_id),
            "run_id": str(self.run_id),
            "job_id": str(self.job_id),
            "engine_pack_id": str(self.engine_pack_id),
            "worker_generation": self.worker_generation,
            "expected_pid": self.expected_pid,
            "endpoint_name": self.endpoint_name,
            "secret_b64": base64.b64encode(self.secret).decode("ascii"),
            "core_capabilities": list(self.core_capabilities),
            "worker_capabilities": list(self.worker_capabilities),
            "protocol_major": self.protocol_major,
            "protocol_minor": self.protocol_minor,
        }


def encode_bootstrap(packet: WorkerBootstrap) -> bytes:
    body = canonical_json_dumps(packet.to_payload()).encode("utf-8")
    if len(body) > _MAX_BOOTSTRAP:
        raise ValueError("bootstrap packet too large")
    return _HEADER.pack(len(body)) + body


def decode_bootstrap(raw: bytes) -> WorkerBootstrap:
    if len(raw) < 4:
        raise ValueError("bootstrap packet truncated")
    (size,) = _HEADER.unpack(raw[:4])
    if size > _MAX_BOOTSTRAP or len(raw) != 4 + size:
        raise ValueError("invalid bootstrap length")
    obj = json_loads_object(raw[4:].decode("utf-8"))
    if obj.get("schema") != 1:
        raise ValueError("unsupported bootstrap schema")
    secret = base64.b64decode(str(obj["secret_b64"]), validate=True)
    return WorkerBootstrap(
        core_instance_id=CoreInstanceId.parse(str(obj["core_instance_id"])),
        worker_session_id=WorkerSessionId.parse(str(obj["worker_session_id"])),
        run_id=JobRunId.parse(str(obj["run_id"])),
        job_id=JobId.parse(str(obj["job_id"])),
        engine_pack_id=EnginePackId.parse(str(obj["engine_pack_id"])),
        worker_generation=int(obj["worker_generation"]),
        expected_pid=int(obj["expected_pid"]),
        endpoint_name=str(obj["endpoint_name"]),
        secret=secret,
        core_capabilities=tuple(str(x) for x in obj.get("core_capabilities", [])),
        worker_capabilities=tuple(str(x) for x in obj.get("worker_capabilities", [])),
        protocol_major=int(obj.get("protocol_major", 1)),
        protocol_minor=int(obj.get("protocol_minor", 0)),
    )


def read_bootstrap_fd(fd: int) -> WorkerBootstrap:
    header = os.read(fd, 4)
    if len(header) != 4:
        raise ValueError("bootstrap header truncated")
    (size,) = _HEADER.unpack(header)
    if size > _MAX_BOOTSTRAP:
        raise ValueError("bootstrap packet too large")
    chunks = bytearray()
    while len(chunks) < size:
        chunk = os.read(fd, size - len(chunks))
        if not chunk:
            raise ValueError("bootstrap payload truncated")
        chunks.extend(chunk)
    packet = decode_bootstrap(header + bytes(chunks))
    if packet.expected_pid != os.getpid():
        raise PermissionError("bootstrap expected PID does not match Worker PID")
    return packet


def read_bootstrap_handle(handle: int) -> WorkerBootstrap:
    """Windows-only inherited HANDLE bootstrap reader.

    A parent CRT fd number is not a child fd identity on Windows. The child receives the raw
    inherited HANDLE and creates its own CRT fd with open_osfhandle. Ownership transfers to that fd.
    """
    if os.name != "nt":
        raise OSError("bootstrap HANDLE mode is Windows-only")
    import msvcrt
    fd = msvcrt.open_osfhandle(int(handle), os.O_RDONLY)
    try:
        return read_bootstrap_fd(fd)
    finally:
        os.close(fd)
