from __future__ import annotations

from collections.abc import Mapping

from booru_studio.common.ids import ClientInstanceId, CommandId, JobId
from booru_studio.common.redaction import redact_input_for_storage
from booru_studio.core.job_service import JobService
from booru_studio.core.projection_service import ProjectionService
from booru_studio.domain.commands import (
    CancelJobCommand, CommandIdentity, CreateJobCommand, MoveQueueJobCommand, PauseJobCommand, ResumeJobCommand,
)
from booru_studio.domain.enums import InputKind, JobKind
from booru_studio.ipc.stream_connection import EnvelopeConnection
from booru_studio.ipc.ui_core_protocol import UiCoreMessage, make_ui_envelope, validate_ui_envelope

_MAX_UI_TEXT_CHARS = 16_384
_MAX_TITLE_CHARS = 4_096


class UiRequestError(ValueError):
    """Malformed or unsupported request at the UI/Core trust boundary."""


def _required_text(payload: Mapping[str, object], key: str, *, limit: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise UiRequestError(f"{key} must be a string")
    value = value.strip()
    if not value:
        raise UiRequestError(f"{key} must not be empty")
    if len(value) > limit:
        raise UiRequestError(f"{key} is too long")
    return value


def _priority(payload: Mapping[str, object]) -> int:
    raw = payload.get("priority", 0)
    if isinstance(raw, bool):
        raise UiRequestError("priority must be an integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise UiRequestError("priority must be an integer") from exc
    if value < -1_000_000 or value > 1_000_000:
        raise UiRequestError("priority is outside the supported range")
    return value


def _public_error(exc: BaseException) -> tuple[str, str]:
    """Return a stable, non-secret-bearing UI error response."""

    if isinstance(exc, UiRequestError):
        return "INVALID_REQUEST", str(exc)[:256]
    if isinstance(exc, KeyError):
        return "NOT_FOUND", "The requested job no longer exists."
    if isinstance(exc, TimeoutError):
        return "CORE_TIMEOUT", "The Core operation timed out."
    if isinstance(exc, ValueError):
        return "COMMAND_REJECTED", "The requested operation is not valid in the current state."
    return "CORE_ERROR", "The Core could not complete the requested operation."


class CoreUiSession:
    """Protocol handler for one UI client over an already-established local connection."""

    def __init__(self, jobs: JobService, projection: ProjectionService) -> None:
        self._jobs = jobs
        self._projection = projection

    @staticmethod
    def _identity(payload: Mapping[str, object]) -> CommandIdentity:
        client = _required_text(payload, "client_instance_id", limit=128)
        command = _required_text(payload, "command_id", limit=128)
        try:
            return CommandIdentity(ClientInstanceId.parse(client), CommandId.parse(command))
        except ValueError as exc:
            raise UiRequestError("invalid command identity") from exc

    def handle(self, envelope):
        """Return exactly one response Envelope without owning transport/event-loop state."""
        message = validate_ui_envelope(envelope)
        try:
            if message is UiCoreMessage.HEALTH_CHECK:
                response = UiCoreMessage.HEALTH_RESPONSE
                payload = {"status": "READY"}
            elif message is UiCoreMessage.SNAPSHOT_REQUEST:
                response = UiCoreMessage.SNAPSHOT_RESPONSE
                payload = self._projection.snapshot()
            elif message is UiCoreMessage.CREATE_JOB:
                raw = envelope.payload
                raw_input = _required_text(raw, "redacted_input", limit=_MAX_UI_TEXT_CHARS)
                raw_title = _required_text(raw, "title", limit=_MAX_TITLE_CHARS)
                try:
                    input_kind = InputKind(_required_text(raw, "input_kind", limit=32))
                    job_kind = JobKind(_required_text(raw, "job_kind", limit=64))
                except ValueError as exc:
                    raise UiRequestError("unsupported input or job kind") from exc
                result = self._jobs.create_job(CreateJobCommand(
                    identity=self._identity(raw), input_kind=input_kind,
                    redacted_input=redact_input_for_storage(raw_input), job_kind=job_kind,
                    title=redact_input_for_storage(raw_title), priority=_priority(raw),
                ))
                response = UiCoreMessage.CREATE_JOB_RESULT
                payload = {"job_id": str(result.job_id), "submission_id": str(result.submission_id),
                           "committed_state_revision": result.committed_state_revision, "replayed": result.replayed}
            elif message is UiCoreMessage.CANCEL_JOB:
                raw = envelope.payload
                try:
                    job_id = JobId.parse(_required_text(raw, "job_id", limit=128))
                except ValueError as exc:
                    raise UiRequestError("invalid job id") from exc
                result = self._jobs.cancel_job(CancelJobCommand(identity=self._identity(raw), job_id=job_id))
                response = UiCoreMessage.CANCEL_JOB_RESULT
                payload = {"job_id": str(result.job_id), "committed_state_revision": result.committed_state_revision, "replayed": result.replayed}
            elif message in {UiCoreMessage.PAUSE_JOB, UiCoreMessage.RESUME_JOB, UiCoreMessage.MOVE_QUEUE_JOB}:
                raw = envelope.payload
                try:
                    job_id = JobId.parse(_required_text(raw, "job_id", limit=128))
                except ValueError as exc:
                    raise UiRequestError("invalid job id") from exc
                identity = self._identity(raw)
                if message is UiCoreMessage.PAUSE_JOB:
                    result = self._jobs.pause_job(PauseJobCommand(identity=identity, job_id=job_id)); response = UiCoreMessage.PAUSE_JOB_RESULT
                elif message is UiCoreMessage.RESUME_JOB:
                    result = self._jobs.resume_job(ResumeJobCommand(identity=identity, job_id=job_id)); response = UiCoreMessage.RESUME_JOB_RESULT
                else:
                    direction = _required_text(raw, "direction", limit=16).upper()
                    if direction not in {"UP", "DOWN"}:
                        raise UiRequestError("queue direction must be UP or DOWN")
                    result = self._jobs.move_queue_job(MoveQueueJobCommand(identity=identity, job_id=job_id, direction=direction)); response = UiCoreMessage.MOVE_QUEUE_JOB_RESULT
                payload = {"job_id": str(result.job_id), "committed_state_revision": result.committed_state_revision, "replayed": result.replayed}
            else:
                raise UiRequestError("unsupported UI-Core request")
        except Exception as exc:
            code, public_message = _public_error(exc)
            response = UiCoreMessage.ERROR
            payload = {"code": code, "message": public_message}
        return make_ui_envelope(response, message_id=envelope.message_id, trace_id=envelope.trace_id, payload=payload)

    def serve_one(self, connection: EnvelopeConnection) -> UiCoreMessage:
        envelope = connection.recv()
        message = validate_ui_envelope(envelope)
        connection.send(self.handle(envelope))
        return message
