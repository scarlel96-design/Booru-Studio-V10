from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from booru_studio.common.ids import EnginePackId, JobId, JobRunId
from booru_studio.domain.enums import RunOutcome


@dataclass(frozen=True, slots=True)
class ExecutionSpecSnapshot:
    values: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(slots=True)
class RuntimePolicy:
    bandwidth_limit_bps: int | None = None
    priority: int = 0
    max_parallel_transfers: int | None = None


@dataclass(slots=True)
class JobRun:
    run_id: JobRunId
    job_id: JobId
    engine_pack_id: EnginePackId
    execution_spec: ExecutionSpecSnapshot
    runtime_policy: RuntimePolicy
    started_at_utc_ms: int
    ended_at_utc_ms: int | None = None
    outcome: RunOutcome | None = None
    worker_generation: int = 0
