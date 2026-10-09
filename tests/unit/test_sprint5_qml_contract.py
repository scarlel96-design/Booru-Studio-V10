from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[2]
QML = ROOT / "src" / "booru_studio" / "ui" / "qml"


def test_qml_shell_contains_required_v10_primary_surfaces() -> None:
    text = (QML / "App.qml").read_text(encoding="utf-8")
    for token in ("DownloadsPage", "QueuePage", "HistoryPage", "SettingsPage", "action.add_queue"):
        assert token in text
    assert "appController.canSubmit" in text
    # Sprint 10 preserves Sprint 5's original requirement (failed submission must keep
    # the user's text) with a stronger async-safe commit acknowledgement.
    assert "appController.submitInput(inputField.text)" in text
    assert "onSubmissionCommitted" in text
    assert "if (inputField.text === rawInput)" in text
    assert "appController.pendingCommand" in text


def test_qml_list_views_enable_delegate_reuse() -> None:
    downloads = (QML / "pages" / "DownloadsPage.qml").read_text(encoding="utf-8")
    queue = (QML / "pages" / "QueuePage.qml").read_text(encoding="utf-8")
    history = (QML / "pages" / "HistoryPage.qml").read_text(encoding="utf-8")
    assert "reuseItems: true" in downloads
    assert "reuseItems: true" in queue
    assert "reuseItems: true" in history


def test_translation_key_sets_are_identical() -> None:
    import json

    ko = json.loads((ROOT / "src" / "booru_studio" / "ui" / "translations" / "ko_KR.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "src" / "booru_studio" / "ui" / "translations" / "en_US.json").read_text(encoding="utf-8"))
    assert set(ko) == set(en)


def test_translation_catalog_switches_languages_and_has_parity() -> None:
    from booru_studio.ui.i18n import TranslationCatalog

    catalog = TranslationCatalog(language="ko")
    catalog.validate_parity()
    assert catalog.text("nav.queue") == "대기열"
    assert catalog.set_language("en") is True
    assert catalog.text("nav.queue") == "Queue"


def test_remote_job_text_is_forced_to_plain_text() -> None:
    card = (QML / "components" / "JobCard.qml").read_text(encoding="utf-8")
    queue = (QML / "pages" / "QueuePage.qml").read_text(encoding="utf-8")
    assert card.count("textFormat: Text.PlainText") >= 2
    assert "textFormat: Text.PlainText" in queue


def test_queue_exposes_cancel_and_history_surfaces_bounded_state() -> None:
    queue = (QML / "pages" / "QueuePage.qml").read_text(encoding="utf-8")
    history = (QML / "pages" / "HistoryPage.qml").read_text(encoding="utf-8")
    assert "appController.cancelJob(model.job_id)" in queue
    assert "appController.historyHasMore" in history


def test_qt_model_preserves_stable_rows_for_data_only_updates() -> None:
    model = (ROOT / "src" / "booru_studio" / "ui" / "qt_models.py").read_text(encoding="utf-8")
    assert "replacement.job_ids == self._data.job_ids" in model
    assert "self.dataChanged.emit" in model
