from __future__ import annotations

from pathlib import Path

from booru_studio.core.source_ui_backend import SourceUiBackend


def test_source_ui_backend_creates_durable_queue_job_and_refreshes(tmp_path: Path) -> None:
    snapshots: list[dict[str, object]] = []
    db_path = tmp_path / "사용자" / "Booru Studio" / "state.sqlite3"
    backend = SourceUiBackend(db_path, snapshots.append)
    try:
        job_id = backend.submit("https://example.test/이미지.jpg")
        assert job_id
        assert snapshots
        latest = snapshots[-1]
        assert latest["queue"][0]["job_id"] == job_id
        assert latest["downloads"][0]["display_input"].endswith("이미지.jpg")
        assert latest["downloads"][0]["kind"] == "UNKNOWN"
    finally:
        backend.close()

    snapshots2: list[dict[str, object]] = []
    backend2 = SourceUiBackend(db_path, snapshots2.append)
    try:
        backend2.refresh()
        assert snapshots2[-1]["queue"][0]["job_id"] == job_id
    finally:
        backend2.close()


def test_source_ui_backend_close_is_idempotent_and_rejects_further_use(tmp_path: Path) -> None:
    import pytest

    backend = SourceUiBackend(tmp_path / "state.sqlite3", lambda _snapshot: None)
    backend.close()
    backend.close()
    with pytest.raises(RuntimeError, match="closed"):
        backend.refresh()


def test_source_ui_backend_redacts_sensitive_url_and_persists_cancel_intent(tmp_path: Path) -> None:
    snapshots: list[dict[str, object]] = []
    backend = SourceUiBackend(tmp_path / "state.sqlite3", snapshots.append)
    try:
        job_id = backend.submit("https://u:p@example.test/a.jpg?token=secret&quality=best#fragment")
        row = snapshots[-1]["downloads"][0]
        assert "secret" not in row["display_input"]
        assert "fragment" not in row["display_input"]
        assert "secret" not in row["title"]
        backend.cancel(job_id)
        assert snapshots[-1]["downloads"][0]["control_intent"] == "CANCEL_REQUESTED"
    finally:
        backend.close()
