from __future__ import annotations

from typing import Any

from booru_studio.core.ui_session import CoreUiSession
from booru_studio.ipc.envelopes import envelope_from_wire_dict, envelope_to_wire_dict
from booru_studio.ipc.framing import FrameDecoder, encode_json_frame
from booru_studio.ipc.qlocal import QLocalUnavailable, create_user_only_server

UI_CORE_MAX_FRAME_BYTES = 2 * 1024 * 1024


def create_ui_core_server(name: str, session: CoreUiSession) -> Any:
    """Create an event-driven same-user QLocal UI server on the Qt-owning thread."""
    try:
        from PySide6.QtCore import QObject
    except ImportError as exc:
        raise QLocalUnavailable("PySide6 QtCore is unavailable") from exc

    class _Server(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.server = create_user_only_server(name)
            self._decoders: dict[object, FrameDecoder] = {}
            self.server.newConnection.connect(self._accept)

        def _accept(self) -> None:
            while self.server.hasPendingConnections():
                socket = self.server.nextPendingConnection()
                self._decoders[socket] = FrameDecoder(max_bytes=UI_CORE_MAX_FRAME_BYTES)
                socket.readyRead.connect(lambda s=socket: self._read(s))
                socket.disconnected.connect(lambda s=socket: self._drop(s))

        def _drop(self, socket) -> None:
            self._decoders.pop(socket, None)
            socket.deleteLater()

        def _read(self, socket) -> None:
            decoder = self._decoders.get(socket)
            if decoder is None:
                return
            try:
                frames = decoder.feed(bytes(socket.readAll()))
                for obj in frames:
                    request = envelope_from_wire_dict(obj)
                    response = session.handle(request)
                    frame = encode_json_frame(envelope_to_wire_dict(response), max_bytes=UI_CORE_MAX_FRAME_BYTES)
                    if socket.write(frame) < 0:
                        raise RuntimeError("QLocalSocket write failed")
            except Exception:
                socket.abort()

        def close(self) -> None:
            for socket in list(self._decoders):
                socket.abort()
            self._decoders.clear()
            self.server.close()

    return _Server()
