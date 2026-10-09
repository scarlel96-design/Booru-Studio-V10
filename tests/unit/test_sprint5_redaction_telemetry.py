from __future__ import annotations

from booru_studio.common.redaction import redact_input_for_storage
from booru_studio.ui.telemetry_overlay import JobTelemetry, TelemetryOverlay


def test_url_redaction_removes_userinfo_fragment_and_all_query_values() -> None:
    raw = "https://user:pass@example.test/path?token=secret&quality=best&Policy=signed#private"
    redacted = redact_input_for_storage(raw)
    assert "user" not in redacted
    assert "pass" not in redacted
    assert "secret" not in redacted
    assert "private" not in redacted
    assert redacted == "https://example.test/path"
    assert "signed" not in redacted


def test_url_redaction_accepts_mixed_case_scheme_and_ipv6() -> None:
    assert redact_input_for_storage("HTTPS://user:pass@[2001:DB8::1]:443/path?unknown_key=secret#part") == (
        "https://[2001:db8::1]:443/path"
    )


def test_telemetry_overlay_rejects_stale_generation_and_run_conflict() -> None:
    overlay = TelemetryOverlay()
    assert overlay.update(JobTelemetry("job", "run-a", 2, bytes_done=10))
    assert not overlay.update(JobTelemetry("job", "run-a", 1, bytes_done=20))
    assert not overlay.update(JobTelemetry("job", "run-b", 2, bytes_done=30))
    assert overlay.get("job").bytes_done == 10
    assert overlay.update(JobTelemetry("job", "run-b", 3, bytes_done=40))
    assert overlay.get("job").run_id == "run-b"
    overlay.invalidate_all()
    assert overlay.get("job") is None


def test_display_sanitizer_strips_bidi_and_control_characters() -> None:
    from booru_studio.common.text_safety import sanitize_display_text

    value = "safe\u202eevil\u0000-name"
    safe = sanitize_display_text(value)
    assert "\u202e" not in safe
    assert "\u0000" not in safe
    assert "safe" in safe and "evil" in safe
