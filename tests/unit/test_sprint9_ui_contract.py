from __future__ import annotations

import json
from pathlib import Path

from booru_studio.ui.action_controller import ActionController
from booru_studio.ui.platform_actions import PlatformActionError, open_file

ROOT = Path(__file__).resolve().parents[2]
QML = ROOT / "src" / "booru_studio" / "ui" / "qml"


def test_action_capabilities_match_lifecycle_semantics() -> None:
    active = ActionController.evaluate(connected=True, stale=False, pending_command=False, selected_lifecycle="ACTIVE")
    paused = ActionController.evaluate(connected=True, stale=False, pending_command=False, selected_lifecycle="PAUSED")
    queued = ActionController.evaluate(connected=True, stale=False, pending_command=False, selected_lifecycle="QUEUED")
    assert active.can_pause and active.can_cancel and not active.can_resume
    assert paused.can_resume and paused.can_cancel and not paused.can_pause
    assert queued.can_pause and queued.can_cancel


def test_product_qml_exposes_controls_phase_error_and_file_actions() -> None:
    downloads = (QML / "pages" / "DownloadsPage.qml").read_text(encoding="utf-8")
    queue = (QML / "pages" / "QueuePage.qml").read_text(encoding="utf-8")
    card = (QML / "components" / "JobCard.qml").read_text(encoding="utf-8")
    for token in ("pauseJob", "resumeJob", "openDownloadedFile", "revealDownloadedFile", "latest_error_code", "primary_file_path"):
        assert token in downloads
    for token in ("moveQueueJob", '"UP"', '"DOWN"', "pauseJob"):
        assert token in queue
    for token in ("Qt.RightButton", "phaseLabel", "POSTPROCESSING", "VERIFYING", "error.label", "action.reveal_file"):
        assert token in card


def test_sprint9_translation_catalogs_remain_exactly_in_parity() -> None:
    base = ROOT / "src" / "booru_studio" / "ui" / "translations"
    en = json.loads((base / "en_US.json").read_text(encoding="utf-8"))
    ko = json.loads((base / "ko_KR.json").read_text(encoding="utf-8"))
    assert set(en) == set(ko)
    for key in ("action.pause", "action.resume", "action.open_file", "action.reveal_file", "phase.postprocessing", "kind.single_media"):
        assert en[key].strip() and ko[key].strip()


def test_platform_file_action_fails_closed_for_missing_path(tmp_path: Path) -> None:
    try:
        open_file(str(tmp_path / "missing.bin"))
    except PlatformActionError as exc:
        assert "no longer available" in str(exc)
    else:
        raise AssertionError("missing file must not be delegated to the OS shell")
