from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path


def main() -> int:
    if os.name != "nt":
        raise SystemExit("Sprint 10 runtime smoke is Windows-only")
    from PySide6.QtCore import QCoreApplication, QTimer
    from booru_studio.common.clock import SystemClock
    from booru_studio.core.job_service import JobService
    from booru_studio.core.projection_service import ProjectionService
    from booru_studio.core.qlocal_ui_server import create_ui_core_server
    from booru_studio.core.ui_session import CoreUiSession
    from booru_studio.ipc.qlocal import connect_local_socket
    from booru_studio.ipc.qt_connection import QtLocalEnvelopeConnection
    from booru_studio.persistence.db_actor import DbActor
    from booru_studio.ui.ipc_client import UiCoreClient

    app=QCoreApplication([]); clock=SystemClock()
    with tempfile.TemporaryDirectory(prefix="보루스튜디오 Sprint10 ") as td:
        db=DbActor(Path(td)/"상태.sqlite3",now_utc_ms=clock.utc_ms()); db.start()
        name=f"booru-v10-smoke-{os.getpid()}"
        server=create_ui_core_server(name,CoreUiSession(JobService(db,clock),ProjectionService(db)))
        result=[]
        def client():
            sock=connect_local_socket(name); conn=QtLocalEnvelopeConnection(sock,max_frame_bytes=2*1024*1024)
            payload=UiCoreClient(conn).snapshot(); result.append(int(payload["state_revision"])); conn.close()
            QTimer.singleShot(0,app.quit)
        threading.Thread(target=client,daemon=True).start()
        QTimer.singleShot(10000,app.quit); app.exec(); server.close(); db.close()
        if result != [0]: raise SystemExit(f"unexpected QLocal result: {result!r}")
    print("SPRINT10 QLOCAL SAME-USER SOURCE RUNTIME: PASS")
    return 0

if __name__=="__main__": raise SystemExit(main())
