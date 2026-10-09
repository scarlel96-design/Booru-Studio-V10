from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[2] / "src" / "booru_studio"


def test_playwright_concrete_adapter_is_worker_owned() -> None:
    for relative in ("core", "ui", "persistence", "domain"):
        for path in (ROOT / relative).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "playwright_browser" not in text, path
            assert "import playwright" not in text, path
            assert "playwright.sync_api" not in text, path


def test_browser_runtime_is_nonpersistent_and_intercepted() -> None:
    text = (ROOT / "engine" / "adapters" / "playwright_browser" / "adapter.py").read_text(encoding="utf-8")
    assert 'channel=self.channel' in text
    assert 'service_workers="block"' in text
    assert 'accept_downloads=False' in text
    assert 'context.route("**/*", route_handler)' in text
    assert 'request.resource_type' in text
    assert 'route.abort("blockedbyclient")' in text
    assert 'context.route_web_socket' in text
    assert 'page.on("popup"' in text
    assert 'bypass_csp=False' in text
    assert 'launch_persistent_context' not in text


def test_web_pipeline_is_worker_owned() -> None:
    text = (ROOT / "worker" / "web_pipeline.py").read_text(encoding="utf-8")
    assert "StaticWebAdapter" in text
    assert "BrowserAssistAdapter" in text
