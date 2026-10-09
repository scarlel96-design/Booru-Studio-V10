from __future__ import annotations

import json
import struct

from booru_studio.ipc.envelopes import Envelope, envelope_from_wire_dict, envelope_to_wire_dict
from booru_studio.ipc.framing import ABSOLUTE_MAX_FRAME_BYTES, encode_json_frame
from booru_studio.ipc.stream_connection import EnvelopeConnection

_HEADER = struct.Struct(">I")


class QtLocalEnvelopeConnection(EnvelopeConnection):
    """Synchronous framing wrapper used by the Worker side of QLocalSocket.

    Runtime behavior requires PySide6 and is intentionally covered by a later Windows gate.
    """

    def __init__(self, socket, *, timeout_ms: int = 5000, max_frame_bytes: int = ABSOLUTE_MAX_FRAME_BYTES) -> None:
        self._socket = socket; self._timeout = timeout_ms; self._max = max_frame_bytes; self._buffer = bytearray()

    def send(self, envelope: Envelope) -> None:
        frame = encode_json_frame(envelope_to_wire_dict(envelope), max_bytes=self._max)
        written = self._socket.write(frame)
        if written < 0 or not self._socket.waitForBytesWritten(self._timeout):
            raise RuntimeError("QLocalSocket write failed")

    def recv(self) -> Envelope:
        return self._recv_with_timeout_ms(self._timeout)

    def recv_timeout(self, timeout_s: float) -> Envelope:
        return self._recv_with_timeout_ms(max(0, int(float(timeout_s) * 1000)))

    def _recv_with_timeout_ms(self, timeout_ms: int) -> Envelope:
        import time
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            if len(self._buffer) >= 4:
                (size,) = _HEADER.unpack(self._buffer[:4])
                if size > self._max: raise ValueError("frame too large")
                if len(self._buffer) >= 4 + size:
                    body = bytes(self._buffer[4:4+size]); del self._buffer[:4+size]
                    obj = json.loads(body.decode("utf-8"))
                    if not isinstance(obj, dict): raise ValueError("frame must be object")
                    return envelope_from_wire_dict(obj)
            if self._socket.bytesAvailable():
                self._buffer.extend(bytes(self._socket.readAll()))
                continue
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if remaining_ms <= 0 or not self._socket.waitForReadyRead(remaining_ms):
                raise TimeoutError("QLocalSocket read timed out")
            self._buffer.extend(bytes(self._socket.readAll()))

    def close(self) -> None:
        self._socket.disconnectFromServer()
