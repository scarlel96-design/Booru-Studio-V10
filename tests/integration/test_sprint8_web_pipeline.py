from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

from booru_studio.worker.web_pipeline import WebResolutionMode, WebResolverPipeline


def test_static_web_pipeline_finds_media_without_browser(tmp_path: Path) -> None:
    root = tmp_path / "web"; root.mkdir()
    (root / "index.html").write_text("<html><title>Page</title><img src='/one.jpg'><video src='/two.mp4'></video></html>", encoding="utf-8")
    (root / "one.jpg").write_bytes(b"image")
    (root / "two.mp4").write_bytes(b"video")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        result = WebResolverPipeline(allow_private_root=True).resolve(
            f"http://127.0.0.1:{server.server_port}/index.html",
            cancel_event=threading.Event(),
            allow_browser_fallback=False,
        )
        assert result.mode is WebResolutionMode.STATIC
        assert len(result.items) == 2
        assert result.presentation is not None
        assert result.presentation.collection.value == "WEB_PAGE"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_browser_fallback_is_used_only_after_empty_static_result() -> None:
    from booru_studio.engine.adapters.playwright_browser.adapter import BrowserAssistResult
    from booru_studio.engine.adapters.static_web.adapter import StaticWebResult
    from booru_studio.engine.contracts import CandidateArtifact, HandoffSafety, NormalizedItemDescriptor, TransferDescriptor

    item = NormalizedItemDescriptor(
        source_identity="browser:test:1", media_kind="VIDEO", display_title="Dynamic",
        source_index=0, discovery_sequence=0,
        candidate_artifacts=(CandidateArtifact(
            "PRIMARY", "dynamic.mp4", TransferDescriptor(
                "https://cdn.example/dynamic.mp4", handoff_safety=HandoffSafety.CONDITIONAL,
            )
        ),),
    )

    class EmptyStatic:
        called = 0
        def discover(self, raw_input: str):
            self.called += 1
            return StaticWebResult(raw_input, "Static", (), 0)

    class Browser:
        called = 0
        def discover(self, raw_input: str, *, cancel_event):
            self.called += 1
            return BrowserAssistResult(raw_input, "Dynamic", (item,), 0, 0)

    static = EmptyStatic(); browser = Browser()
    result = WebResolverPipeline(static=static, browser=browser).resolve(
        "https://public.example/page", cancel_event=threading.Event(),
    )
    assert static.called == 1 and browser.called == 1
    assert result.mode is WebResolutionMode.BROWSER
    assert result.presentation is not None and result.presentation.mode.value == "INDIVIDUAL"
