from pathlib import Path

from booru_studio.ipc.ui_core_protocol import UiCoreMessage, make_ui_envelope, validate_ui_envelope


def test_health_message_is_control_plane():
    env=make_ui_envelope(UiCoreMessage.HEALTH_CHECK,message_id="h",payload={})
    assert validate_ui_envelope(env) is UiCoreMessage.HEALTH_CHECK
    assert env.plane.value == "CONTROL"


def test_native_supervisor_requires_qlocal_health_probe_before_hang_kill():
    src=Path("native/supervisor/src/main.rs").read_text(encoding="utf-8")
    assert "qlocal_health" in src
    assert "HEALTH_CHECK" in src and "HEALTH_RESPONSE" in src
    assert "age>8_000 && qlocal_health(&endpoint)" in src
    assert "else if age>20_000" in src


def test_native_health_probe_never_blocking_reads_before_bounded_peek():
    src=Path("native/supervisor/src/main.rs").read_text(encoding="utf-8")
    assert "fn wait_pipe_bytes" in src
    assert "for _ in 0..75" in src
    assert "PeekNamedPipe" in src
    assert "if !wait_pipe_bytes(h,4)" in src
    assert "if !wait_pipe_bytes(h,n as u32)" in src
