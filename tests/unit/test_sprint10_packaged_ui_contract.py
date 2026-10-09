from pathlib import Path


def test_packaged_ui_fails_closed_without_core_endpoint():
    app=Path("src/booru_studio/ui/app.py").read_text(encoding="utf-8")
    assert "BOORU_STUDIO_PACKAGED" in app
    assert "if packaged and not endpoint" in app
    assert "return 4" in app


def test_input_is_cleared_only_after_core_commit_signal():
    app=Path("src/booru_studio/ui/app.py").read_text(encoding="utf-8")
    qml=Path("src/booru_studio/ui/qml/App.qml").read_text(encoding="utf-8")
    assert "submissionCommitted = Signal(str)" in app
    assert "onSubmissionCommitted" in qml
    assert "if (appController.submitInput(inputField.text))" not in qml
