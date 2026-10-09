from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from booru_studio.common.clock import SystemClock
from booru_studio.core.job_service import JobService
from booru_studio.core.projection_service import ProjectionService
from booru_studio.core.ui_session import CoreUiSession
from booru_studio.persistence.db_actor import DbActor


def _open_heartbeat_fd(raw_handle: int | None) -> int | None:
    if raw_handle is None:
        return None
    if os.name != "nt":
        raise OSError("Supervisor heartbeat HANDLE is Windows-only")
    import msvcrt
    fd = msvcrt.open_osfhandle(int(raw_handle), 0)
    # The Supervisor intentionally grants this HANDLE only to Core. Do not let later Worker/
    # FFmpeg/browser child creation accidentally extend the liveness lease by inheriting it.
    os.set_inheritable(fd, False)
    return fd


def _write_heartbeat(fd: int, seq: int) -> bool:
    """Called by the Qt event loop: if the event loop hangs, heartbeats stop by construction."""
    try:
        os.write(fd, f"HB1 {os.getpid()} {seq}\n".encode("ascii"))
        return True
    except (BrokenPipeError, OSError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--state-db", type=Path, required=True)
    parser.add_argument("--supervisor-heartbeat-handle", type=int)
    args = parser.parse_args(argv)
    try:
        from PySide6.QtCore import QCoreApplication, QTimer
    except ImportError:
        print("PySide6 is required for the production Core runtime", file=sys.stderr)
        return 2
    from booru_studio.core.qlocal_ui_server import create_ui_core_server

    clock = SystemClock()
    db = DbActor(args.state_db, now_utc_ms=clock.utc_ms())
    db.start()
    heartbeat_fd = _open_heartbeat_fd(args.supervisor_heartbeat_handle)
    app = QCoreApplication(sys.argv[:1])
    heartbeat_timer = None
    heartbeat_seq = 0
    if heartbeat_fd is not None:
        heartbeat_timer = QTimer()
        heartbeat_timer.setInterval(2000)
        def heartbeat() -> None:
            nonlocal heartbeat_seq, heartbeat_fd
            heartbeat_seq += 1
            if heartbeat_fd is not None and not _write_heartbeat(heartbeat_fd, heartbeat_seq):
                try:
                    os.close(heartbeat_fd)
                except OSError:
                    pass
                heartbeat_fd = None
                heartbeat_timer.stop()
        heartbeat_timer.timeout.connect(heartbeat)
        heartbeat_timer.start()
    server = create_ui_core_server(args.endpoint, CoreUiSession(JobService(db, clock), ProjectionService(db)))
    try:
        return app.exec()
    finally:
        server.close()
        if heartbeat_timer is not None:
            heartbeat_timer.stop()
        if heartbeat_fd is not None:
            try:
                os.close(heartbeat_fd)
            except OSError:
                pass
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
