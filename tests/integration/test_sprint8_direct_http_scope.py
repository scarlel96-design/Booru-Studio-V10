from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

from booru_studio.common.ids import ArtifactId
from booru_studio.engine.adapters.direct_http import DirectHttpTransfer, DirectHttpWorker
from booru_studio.scheduler.coordinator import NetworkAdmissionController


class RedirectHandler(http.server.BaseHTTPRequestHandler):
    destination = ""
    def do_GET(self):
        self.send_response(302); self.send_header("Location", self.destination); self.end_headers()
    def log_message(self, *args): pass


class TargetHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *args): pass


def test_root_or_public_direct_http_blocks_redirect_to_different_private_origin(tmp_path: Path) -> None:
    target = http.server.ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
    target_thread = threading.Thread(target=target.serve_forever, daemon=True); target_thread.start()
    redirect = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    RedirectHandler.destination = f"http://127.0.0.1:{target.server_port}/secret"
    redirect_thread = threading.Thread(target=redirect.serve_forever, daemon=True); redirect_thread.start()
    try:
        root = f"http://127.0.0.1:{redirect.server_port}/start"
        transfer = DirectHttpTransfer(
            artifact_id=ArtifactId.new(), generation=1, url=root,
            staging_path=tmp_path / "x.part", sidecar_path=tmp_path / "x.resume.json",
            source_fingerprint="scope-test", redirect_policy="HTTP_OR_HTTPS",
            network_scope_policy="ROOT_OR_PUBLIC", network_scope_root=root,
        )
        worker = DirectHttpWorker()
        admission = NetworkAdmissionController(1)
        try:
            with pytest.raises(RuntimeError, match="network-scope"):
                worker.transfer(transfer, threading.Event(), admission)
        finally:
            worker.close()
    finally:
        redirect.shutdown(); redirect.server_close(); redirect_thread.join(timeout=2)
        target.shutdown(); target.server_close(); target_thread.join(timeout=2)
