from __future__ import annotations

from enum import StrEnum
from typing import Mapping

from booru_studio.ipc.envelopes import Envelope, MessagePlane, ProtocolFamily, ProtocolVersion

UI_CORE_VERSION = ProtocolVersion(1, 0)


class UiCoreMessage(StrEnum):
    HEALTH_CHECK = "HEALTH_CHECK"
    HEALTH_RESPONSE = "HEALTH_RESPONSE"
    SNAPSHOT_REQUEST = "SNAPSHOT_REQUEST"
    SNAPSHOT_RESPONSE = "SNAPSHOT_RESPONSE"
    CREATE_JOB = "CREATE_JOB"
    CREATE_JOB_RESULT = "CREATE_JOB_RESULT"
    CANCEL_JOB = "CANCEL_JOB"
    CANCEL_JOB_RESULT = "CANCEL_JOB_RESULT"
    PAUSE_JOB = "PAUSE_JOB"
    PAUSE_JOB_RESULT = "PAUSE_JOB_RESULT"
    RESUME_JOB = "RESUME_JOB"
    RESUME_JOB_RESULT = "RESUME_JOB_RESULT"
    MOVE_QUEUE_JOB = "MOVE_QUEUE_JOB"
    MOVE_QUEUE_JOB_RESULT = "MOVE_QUEUE_JOB_RESULT"
    ERROR = "ERROR"


_PLANES: dict[UiCoreMessage, MessagePlane] = {
    UiCoreMessage.HEALTH_CHECK: MessagePlane.CONTROL,
    UiCoreMessage.HEALTH_RESPONSE: MessagePlane.CONTROL,
    UiCoreMessage.SNAPSHOT_REQUEST: MessagePlane.STATE,
    UiCoreMessage.SNAPSHOT_RESPONSE: MessagePlane.STATE,
    UiCoreMessage.CREATE_JOB: MessagePlane.COMMAND,
    UiCoreMessage.CREATE_JOB_RESULT: MessagePlane.COMMAND,
    UiCoreMessage.CANCEL_JOB: MessagePlane.COMMAND,
    UiCoreMessage.CANCEL_JOB_RESULT: MessagePlane.COMMAND,
    UiCoreMessage.PAUSE_JOB: MessagePlane.COMMAND,
    UiCoreMessage.PAUSE_JOB_RESULT: MessagePlane.COMMAND,
    UiCoreMessage.RESUME_JOB: MessagePlane.COMMAND,
    UiCoreMessage.RESUME_JOB_RESULT: MessagePlane.COMMAND,
    UiCoreMessage.MOVE_QUEUE_JOB: MessagePlane.COMMAND,
    UiCoreMessage.MOVE_QUEUE_JOB_RESULT: MessagePlane.COMMAND,
    UiCoreMessage.ERROR: MessagePlane.CONTROL,
}


def make_ui_envelope(
    message: UiCoreMessage,
    *,
    message_id: str,
    payload: Mapping[str, object],
    trace_id: str | None = None,
) -> Envelope:
    return Envelope(
        family=ProtocolFamily.UI_CORE,
        version=UI_CORE_VERSION,
        plane=_PLANES[message],
        message_type=message.value,
        message_id=message_id,
        trace_id=trace_id,
        payload=payload,
    )


def validate_ui_envelope(envelope: Envelope) -> UiCoreMessage:
    if envelope.family is not ProtocolFamily.UI_CORE:
        raise ValueError("unexpected protocol family")
    if envelope.version.major != UI_CORE_VERSION.major:
        raise ValueError("incompatible ui-core protocol major")
    try:
        message = UiCoreMessage(envelope.message_type)
    except ValueError as exc:
        raise ValueError("unknown ui-core message") from exc
    if envelope.plane is not _PLANES[message]:
        raise ValueError("ui-core message is on the wrong logical plane")
    return message
