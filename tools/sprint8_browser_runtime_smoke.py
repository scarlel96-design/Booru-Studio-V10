from __future__ import annotations

import functools
import http.server
import tempfile
import threading
from pathlib import Path
from importlib.metadata import version

from booru_studio.engine.adapters.playwright_browser import BrowserAssistAdapter, PlaywrightPythonBackend
from booru_studio.engine.adapters.playwright_browser.adapter import PLAYWRIGHT_PIN


def main() -> int:
    installed = version("playwright")
    if installed != PLAYWRIGHT_PIN:
        raise RuntimeError(f"Playwright mismatch: expected {PLAYWRIGHT_PIN}, got {installed}")
    PlaywrightPythonBackend._verify_runtime()

    with tempfile.TemporaryDirectory(prefix="booru-s8-browser-") as tmp:
        root = Path(tmp)
        (root / "media.jpg").write_bytes(b"not-decoded-by-smoke")
        (root / "index.html").write_text(
            """<!doctype html><html><head><title>Sprint 8 Browser Smoke</title></head><body>
            <script>
              const good = document.createElement('img'); good.src='/media.jpg'; document.body.appendChild(good);
              const blocked = document.createElement('img'); blocked.src='http://127.0.0.1:1/private.jpg'; document.body.appendChild(blocked);
            </script></body></html>""",
            encoding="utf-8",
        )
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/index.html"
            result = BrowserAssistAdapter(allow_private_root=True).discover(
                url, cancel_event=threading.Event(), timeout_s=10,
            )
            if result.page_title != "Sprint 8 Browser Smoke":
                raise RuntimeError("Edge/Playwright page-title smoke failed")
            if not any("media.jpg" in item.candidate_artifacts[0].descriptor.url for item in result.items):
                raise RuntimeError("browser media observation smoke found no same-origin media")
            if result.blocked_request_count + result.blocked_candidate_count < 1:
                raise RuntimeError("browser network-scope smoke did not block the cross-origin private target")
            print(f"playwright={installed} channel=msedge media_items={len(result.items)} blocked={result.blocked_request_count + result.blocked_candidate_count}")
            return 0
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
