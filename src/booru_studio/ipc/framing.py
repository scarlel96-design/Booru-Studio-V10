from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import Any

ABSOLUTE_MAX_FRAME_BYTES = 8 * 1024 * 1024
_HEADER = struct.Struct(">I")


def encode_json_frame(payload: dict[str, Any], *, max_bytes: int = ABSOLUTE_MAX_FRAME_BYTES) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(body) > max_bytes:
        raise ValueError("frame exceeds configured maximum")
    return _HEADER.pack(len(body)) + body


@dataclass(slots=True)
class FrameDecoder:
    max_bytes: int = ABSOLUTE_MAX_FRAME_BYTES
    _buffer: bytearray = field(default_factory=bytearray, init=False, repr=False)

    def feed(self, chunk: bytes) -> list[dict[str, Any]]:
        self._buffer.extend(chunk)
        frames: list[dict[str, Any]] = []
        while True:
            if len(self._buffer) < _HEADER.size:
                return frames
            (length,) = _HEADER.unpack_from(self._buffer)
            if length > self.max_bytes:
                self._buffer.clear()
                raise ValueError("declared frame exceeds configured maximum")
            total = _HEADER.size + length
            if len(self._buffer) < total:
                return frames
            body = bytes(self._buffer[_HEADER.size:total])
            del self._buffer[:total]
            decoded = json.loads(body.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise ValueError("top-level IPC frame must be a JSON object")
            frames.append(decoded)
