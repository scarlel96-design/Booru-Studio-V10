from booru_studio.ipc.envelopes import envelope_from_wire_dict, envelope_to_wire_dict
from booru_studio.ipc.ui_core_protocol import UiCoreMessage, make_ui_envelope, validate_ui_envelope


def test_common_wire_decoder_does_not_force_core_worker_family():
    original=make_ui_envelope(UiCoreMessage.SNAPSHOT_REQUEST,message_id="m1",payload={})
    decoded=envelope_from_wire_dict(envelope_to_wire_dict(original))
    assert validate_ui_envelope(decoded) is UiCoreMessage.SNAPSHOT_REQUEST
