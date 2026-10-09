from pathlib import Path


def test_native_supervisor_has_no_product_semantics_dependencies():
    src=Path("native/supervisor/src/main.rs").read_text(encoding="utf-8")
    banned=["sqlite","gallery-dl","yt-dlp","playwright","ffmpeg","queue_repository","job_repository"]
    assert not any(x in src.lower() for x in banned)


def test_ui_remote_backend_never_imports_core_or_persistence():
    src=Path("src/booru_studio/ui/remote_backend.py").read_text(encoding="utf-8")
    assert "booru_studio.core" not in src
    assert "booru_studio.persistence" not in src
