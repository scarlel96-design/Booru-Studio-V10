from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import requests

from booru_studio.engine.adapters.static_web import StaticWebAdapter


def test_static_web_retries_broken_html_stream() -> None:
    class Response:
        status_code = 200
        headers = {"Content-Type": "text/html"}

        def __init__(self, broken: bool) -> None:
            self.broken = broken

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def iter_content(self, _size: int):
            if self.broken:
                raise requests.exceptions.ChunkedEncodingError("connection reset")
            yield b"<html><head><title>Recovered</title></head></html>"

    class Session:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}
            self.calls = 0

        def get(self, *_args, **_kwargs):
            self.calls += 1
            return Response(self.calls == 1)

        def close(self) -> None:
            return None

    session = Session()
    adapter = StaticWebAdapter(session=session, allow_private_root=True)
    result = adapter.discover("http://127.0.0.1/page")
    assert result.page_title == "Recovered"
    assert session.calls == 2


def test_static_web_extracts_media_and_keeps_signed_url_ephemeral(tmp_path: Path) -> None:
    root = tmp_path / "site"; root.mkdir()
    (root / "index.html").write_text("""
      <html><head><title>Static page</title><meta property='og:image' content='/hero.jpg?token=SECRET'></head>
      <body><img src='/a.webp' alt='A'><video><source src='/movie.mp4' type='video/mp4'></video></body></html>
    """, encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    adapter = StaticWebAdapter(allow_private_root=True)
    try:
        url = f"http://127.0.0.1:{server.server_port}/index.html"
        result = adapter.discover(url)
        assert result.page_title == "Static page"
        assert len(result.items) == 3
        serialized = repr([(item.sanitized_metadata, item.source_identity) for item in result.items])
        assert "SECRET" not in serialized
        signed = [c.descriptor for item in result.items for c in item.candidate_artifacts if "hero.jpg" in c.descriptor.url][0]
        assert "token=SECRET" in signed.url
        assert signed.network_scope_policy == "ROOT_OR_PUBLIC"
        assert signed.network_scope_root == url
        assert signed.diagnostic_view()["has_network_scope_root"] is True
        assert "SECRET" not in repr(signed.diagnostic_view())
    finally:
        adapter.close(); server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_static_web_bounds_html_size(tmp_path: Path) -> None:
    root = tmp_path / "large"; root.mkdir()
    (root / "index.html").write_bytes(b"<html>" + b"x" * (4 * 1024 * 1024 + 1) + b"</html>")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    adapter = StaticWebAdapter(allow_private_root=True)
    try:
        import pytest
        with pytest.raises(Exception):
            adapter.discover(f"http://127.0.0.1:{server.server_port}/index.html")
    finally:
        adapter.close(); server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_static_web_candidate_count_is_bounded(tmp_path: Path) -> None:
    root = tmp_path / "many"; root.mkdir()
    tags = "".join(f"<img src='/i/{i}.jpg'>" for i in range(2500))
    (root / "index.html").write_text(f"<html><body>{tags}</body></html>", encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    adapter = StaticWebAdapter(allow_private_root=True)
    try:
        result = adapter.discover(f"http://127.0.0.1:{server.server_port}/index.html")
        assert len(result.items) == 2000
    finally:
        adapter.close(); server.shutdown(); server.server_close(); thread.join(timeout=2)
