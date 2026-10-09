from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[2] / "src" / "booru_studio"


def test_yt_dlp_concrete_adapter_is_worker_owned_not_core_or_ui() -> None:
    for relative in ("core", "ui", "persistence", "domain"):
        for path in (ROOT / relative).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "engine.adapters.yt_dlp" not in text, path
            assert "import yt_dlp" not in text, path


def test_media_pipeline_is_in_worker_layer() -> None:
    text = (ROOT / "worker" / "media_pipeline.py").read_text(encoding="utf-8")
    assert "engine.adapters.yt_dlp" in text
    assert "engine.adapters.ffmpeg" in text
