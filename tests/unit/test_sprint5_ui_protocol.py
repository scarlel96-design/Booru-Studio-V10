from __future__ import annotations

import pytest

from booru_studio.ipc.envelopes import Envelope, MessagePlane, ProtocolFamily, ProtocolVersion
from booru_studio.ipc.ui_core_protocol import UiCoreMessage, make_ui_envelope, validate_ui_envelope


def test_ui_core_protocol_round_trip_validation() -> None:
    envelope = make_ui_envelope(
        UiCoreMessage.SNAPSHOT_REQUEST,
        message_id="snap-1",
        payload={"subscription_id": "main"},
    )
    assert validate_ui_envelope(envelope) is UiCoreMessage.SNAPSHOT_REQUEST
    assert envelope.family is ProtocolFamily.UI_CORE
    assert envelope.plane is MessagePlane.STATE


def test_ui_core_protocol_rejects_wrong_family_and_plane() -> None:
    wrong_family = Envelope(
        family=ProtocolFamily.CORE_WORKER,
        version=ProtocolVersion(1, 0),
        plane=MessagePlane.STATE,
        message_type=UiCoreMessage.SNAPSHOT_REQUEST.value,
        message_id="x",
        trace_id=None,
        payload={},
    )
    with pytest.raises(ValueError):
        validate_ui_envelope(wrong_family)
    wrong_plane = Envelope(
        family=ProtocolFamily.UI_CORE,
        version=ProtocolVersion(1, 0),
        plane=MessagePlane.COMMAND,
        message_type=UiCoreMessage.SNAPSHOT_REQUEST.value,
        message_id="x",
        trace_id=None,
        payload={},
    )
    with pytest.raises(ValueError):
        validate_ui_envelope(wrong_plane)
