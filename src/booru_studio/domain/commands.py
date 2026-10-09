from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from booru_studio.common.ids import (
    ClientInstanceId,
    CommandId,
    EnginePackId,
    JobId,
    JobRunId,
    StorageTargetId,
    SubmissionId,
)
from booru_studio.domain.enums import InputKind, JobKind
from booru_studio.domain.run import ExecutionSpecSnapshot, RuntimePolicy


class CommandType(StrEnum):
    CREATE_JOB = "CREATE_JOB"
    CANCEL_JOB = "CANCEL_JOB"
    PAUSE_JOB = "PAUSE_JOB"
    RESUME_JOB = "RESUME_JOB"
    MOVE_QUEUE_JOB = "MOVE_QUEUE_JOB"


@dataclass(frozen=True, slots=True)
class CommandIdentity:
    client_instance_id: ClientInstanceId
    command_id: CommandId


@dataclass(frozen=True, slots=True)
class CreateJobCommand:
    identity: CommandIdentity
    input_kind: InputKind
    redacted_input: str
    job_kind: JobKind
    title: str
    priority: int = 0
    storage_target_id: StorageTargetId | None = None
    storage_target_generation: int | None = None

    def request_payload(self) -> dict[str, Any]:
        return {
            "input_kind": self.input_kind.value,
            "redacted_input": self.redacted_input,
            "job_kind": self.job_kind.value,
            "title": self.title,
            "priority": self.priority,
            "storage_target_id": (
                str(self.storage_target_id) if self.storage_target_id is not None else None
            ),
            "storage_target_generation": self.storage_target_generation,
        }


@dataclass(frozen=True, slots=True)
class CreateJobResult:
    submission_id: SubmissionId
    job_id: JobId
    committed_state_revision: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class StartJobRunRequest:
    job_id: JobId
    engine_pack_id: EnginePackId
    execution_spec: ExecutionSpecSnapshot
    runtime_policy: RuntimePolicy
    worker_generation: int = 0


@dataclass(frozen=True, slots=True)
class StartJobRunResult:
    run_id: JobRunId
    job_id: JobId
    committed_state_revision: int


@dataclass(frozen=True, slots=True)
class CancelJobCommand:
    identity: CommandIdentity
    job_id: JobId

    def request_payload(self) -> dict[str, Any]:
        return {"job_id": str(self.job_id)}


@dataclass(frozen=True, slots=True)
class CancelJobResult:
    job_id: JobId
    committed_state_revision: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class PauseJobCommand:
    identity: CommandIdentity
    job_id: JobId

    def request_payload(self) -> dict[str, Any]:
        return {"job_id": str(self.job_id)}


@dataclass(frozen=True, slots=True)
class ResumeJobCommand:
    identity: CommandIdentity
    job_id: JobId

    def request_payload(self) -> dict[str, Any]:
        return {"job_id": str(self.job_id)}


@dataclass(frozen=True, slots=True)
class MoveQueueJobCommand:
    identity: CommandIdentity
    job_id: JobId
    direction: str

    def request_payload(self) -> dict[str, Any]:
        return {"job_id": str(self.job_id), "direction": self.direction}


@dataclass(frozen=True, slots=True)
class JobControlResult:
    job_id: JobId
    committed_state_revision: int
    replayed: bool = False
