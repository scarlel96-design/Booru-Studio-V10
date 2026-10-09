from pathlib import Path


def test_core_heartbeat_is_qt_event_loop_owned_not_background_thread():
    src=Path("src/booru_studio/core/runtime_main.py").read_text(encoding="utf-8")
    assert "QTimer" in src and "heartbeat_timer.timeout.connect" in src
    assert "threading.Thread" not in src


def test_qlocal_names_are_opaque_and_user_only():
    src=Path("src/booru_studio/ipc/qlocal.py").read_text(encoding="utf-8")
    assert "UserAccessOption" in src
    assert "_validate_local_name" in src


def test_qml_shell_consumes_semantic_design_tokens():
    app=Path("src/booru_studio/ui/qml/App.qml").read_text(encoding="utf-8")
    nav=Path("src/booru_studio/ui/qml/components/NavButton.qml").read_text(encoding="utf-8")
    card=Path("src/booru_studio/ui/qml/components/JobCard.qml").read_text(encoding="utf-8")
    assert "DesignTokens.windowBackground" in app
    assert "DesignTokens.minimumHitTarget" in nav
    assert "DesignTokens.contentSurface" in card


def test_core_marks_supervisor_heartbeat_fd_non_inheritable():
    src=Path("src/booru_studio/core/runtime_main.py").read_text(encoding="utf-8")
    assert "os.set_inheritable(fd, False)" in src
