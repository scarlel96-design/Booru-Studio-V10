from __future__ import annotations

"""Production-target Qt local IPC adapter.

This module is import-safe without PySide6. Runtime construction requires PySide6 and is
intentionally left for the Windows/PySide runtime gate; Sprint 3 source QA exercises the
same framed protocol over the explicit stdio harness instead.
"""

from typing import Any


class QLocalUnavailable(RuntimeError):
    pass


def _validate_local_name(name: str) -> str:
    value = str(name).strip()
    if not value or len(value) > 240:
        raise ValueError("invalid local IPC endpoint name")
    if any(ch in value for ch in ("\\", "/", "\x00")):
        raise ValueError("local IPC endpoint must be an opaque name, not a path")
    return value


def create_user_only_server(name: str) -> Any:
    name = _validate_local_name(name)
    try:
        from PySide6.QtNetwork import QLocalServer
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise QLocalUnavailable("PySide6 QLocalServer is unavailable") from exc
    server = QLocalServer()
    # UserAccessOption is the intended Windows access boundary.
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(name):
        raise RuntimeError(server.errorString())
    return server


def connect_local_socket(name: str, *, timeout_ms: int = 5000) -> Any:
    name = _validate_local_name(name)
    if timeout_ms <= 0 or timeout_ms > 30_000:
        raise ValueError("invalid local IPC timeout")
    try:
        from PySide6.QtNetwork import QLocalSocket
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise QLocalUnavailable("PySide6 QLocalSocket is unavailable") from exc
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(timeout_ms):
        raise RuntimeError(socket.errorString())
    return socket
