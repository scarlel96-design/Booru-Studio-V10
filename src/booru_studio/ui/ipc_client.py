from __future__ import annotations

from typing import Any

from booru_studio.common.ids import ClientInstanceId, CommandId
from booru_studio.ipc.stream_connection import EnvelopeConnection
from booru_studio.ipc.ui_core_protocol import UiCoreMessage, make_ui_envelope, validate_ui_envelope


class UiCoreCommandError(RuntimeError):
    """Core rejected a valid UI-Core request; transport may still be healthy."""


class UiCoreClient:
    def __init__(self, connection: EnvelopeConnection, *, client_instance_id: ClientInstanceId | None = None) -> None:
        self._connection = connection
        self._client_id = client_instance_id or ClientInstanceId.new()

    def _exchange(
        self,
        message: UiCoreMessage,
        payload: dict[str, object],
        *,
        command_id: CommandId | None = None,
    ) -> tuple[UiCoreMessage, dict[str, Any]]:
        command_id = command_id or CommandId.new()
        message_id = str(command_id)
        request = dict(payload)
        if message in {UiCoreMessage.CREATE_JOB, UiCoreMessage.CANCEL_JOB, UiCoreMessage.PAUSE_JOB, UiCoreMessage.RESUME_JOB, UiCoreMessage.MOVE_QUEUE_JOB}:
            request["client_instance_id"] = str(self._client_id)
            request["command_id"] = str(command_id)
        self._connection.send(make_ui_envelope(message, message_id=message_id, payload=request))
        reply = self._connection.recv()
        reply_type = validate_ui_envelope(reply)
        if reply.message_id != message_id:
            raise ValueError("UI-Core response message_id mismatch")
        data = {str(k): v for k, v in reply.payload.items()}
        if reply_type is UiCoreMessage.ERROR:
            raise UiCoreCommandError(str(data.get("message") or data.get("code") or "Core command failed"))
        return reply_type, data

    def snapshot(self) -> dict[str, Any]:
        reply_type, payload = self._exchange(UiCoreMessage.SNAPSHOT_REQUEST, {})
        if reply_type is not UiCoreMessage.SNAPSHOT_RESPONSE:
            raise ValueError("unexpected snapshot response")
        return payload

    def create_job(
        self, *, input_kind: str, redacted_input: str, job_kind: str, title: str, priority: int = 0,
        command_id: CommandId | None = None,
    ) -> dict[str, Any]:
        reply_type, payload = self._exchange(UiCoreMessage.CREATE_JOB, {
            "input_kind": input_kind,
            "redacted_input": redacted_input,
            "job_kind": job_kind,
            "title": title,
            "priority": priority,
        }, command_id=command_id)
        if reply_type is not UiCoreMessage.CREATE_JOB_RESULT:
            raise ValueError("unexpected create-job response")
        return payload

    def cancel_job(self, job_id: str, *, command_id: CommandId | None = None) -> dict[str, Any]:
        reply_type, payload = self._exchange(UiCoreMessage.CANCEL_JOB, {"job_id": job_id}, command_id=command_id)
        if reply_type is not UiCoreMessage.CANCEL_JOB_RESULT:
            raise ValueError("unexpected cancel-job response")
        return payload


    def pause_job(self, job_id: str, *, command_id: CommandId | None = None) -> dict[str, Any]:
        reply_type, payload = self._exchange(UiCoreMessage.PAUSE_JOB, {"job_id": job_id}, command_id=command_id)
        if reply_type is not UiCoreMessage.PAUSE_JOB_RESULT:
            raise ValueError("unexpected pause-job response")
        return payload

    def resume_job(self, job_id: str, *, command_id: CommandId | None = None) -> dict[str, Any]:
        reply_type, payload = self._exchange(UiCoreMessage.RESUME_JOB, {"job_id": job_id}, command_id=command_id)
        if reply_type is not UiCoreMessage.RESUME_JOB_RESULT:
            raise ValueError("unexpected resume-job response")
        return payload

    def move_queue_job(self, job_id: str, direction: str, *, command_id: CommandId | None = None) -> dict[str, Any]:
        reply_type, payload = self._exchange(UiCoreMessage.MOVE_QUEUE_JOB, {"job_id": job_id, "direction": direction}, command_id=command_id)
        if reply_type is not UiCoreMessage.MOVE_QUEUE_JOB_RESULT:
            raise ValueError("unexpected move-queue response")
        return payload
