from __future__ import annotations

import io
import os
import select
import struct
import time
from collections import deque
from typing import Any, BinaryIO

from booru_studio.ipc.envelopes import Envelope, envelope_from_wire_dict, envelope_to_wire_dict
from booru_studio.ipc.framing import ABSOLUTE_MAX_FRAME_BYTES, FrameDecoder, encode_json_frame

_HEADER = struct.Struct(">I")


class EnvelopeConnection:
    def send(self, envelope: Envelope) -> None:  # pragma: no cover - protocol interface
        raise NotImplementedError
    def recv(self) -> Envelope:  # pragma: no cover - protocol interface
        raise NotImplementedError
    def recv_timeout(self, timeout_s: float) -> Envelope:  # pragma: no cover - protocol interface
        raise NotImplementedError
    def close(self) -> None:  # pragma: no cover - protocol interface
        raise NotImplementedError


class StreamEnvelopeConnection(EnvelopeConnection):
    def __init__(self, reader: BinaryIO, writer: BinaryIO, *, max_frame_bytes: int = ABSOLUTE_MAX_FRAME_BYTES) -> None:
        self._reader = reader; self._writer = writer; self._max = max_frame_bytes
        self._decoder = FrameDecoder(max_bytes=max_frame_bytes)
        self._pending: deque[dict[str, Any]] = deque()

    def send(self, envelope: Envelope) -> None:
        frame = encode_json_frame(envelope_to_wire_dict(envelope), max_bytes=self._max)
        self._writer.write(frame); self._writer.flush()

    def recv(self) -> Envelope:
        if os.name != "nt" and self._pollable_fd() is not None:
            return self._recv_fd(None)
        header = self._read_exact(4)
        (size,) = _HEADER.unpack(header)
        if size > self._max:
            raise ValueError("declared frame exceeds configured maximum")
        body = self._read_exact(size)
        import json
        obj = json.loads(body.decode("utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("top-level frame must be object")
        return envelope_from_wire_dict(obj)

    def recv_timeout(self, timeout_s: float) -> Envelope:
        if os.name == "nt":
            raise NotImplementedError("source stream timeout is POSIX-only")
        if self._pollable_fd() is None:
            raise NotImplementedError("stream does not expose a pollable file descriptor")
        return self._recv_fd(max(0.0, float(timeout_s)))

    def _pollable_fd(self) -> int | None:
        try:
            return self._reader.fileno()
        except (AttributeError, io.UnsupportedOperation):
            return None

    def _recv_fd(self, timeout_s: float | None) -> Envelope:
        fd = self._pollable_fd()
        if fd is None:
            raise NotImplementedError("stream does not expose a pollable file descriptor")
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while not self._pending:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                raise TimeoutError("IPC stream read timed out")
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                raise EOFError("IPC stream closed")
            self._pending.extend(self._decoder.feed(chunk))
        return envelope_from_wire_dict(self._pending.popleft())

    def _read_exact(self, count: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < count:
            data = self._reader.read(count - len(chunks))
            if not data:
                raise EOFError("IPC stream closed")
            chunks.extend(data)
        return bytes(chunks)

    def close(self) -> None:
        for stream in (self._writer, self._reader):
            try: stream.close()
            except Exception: pass
