from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JobTelemetry:
    job_id: str
    run_id: str
    generation: int
    bytes_done: int | None = None
    bytes_total: int | None = None
    speed_bps: float | None = None
    eta_seconds: float | None = None


class TelemetryOverlay:
    """Transient run/generation-fenced telemetry; never durable or authoritative."""

    def __init__(self) -> None:
        self._by_job: dict[str, JobTelemetry] = {}

    def update(self, telemetry: JobTelemetry) -> bool:
        current = self._by_job.get(telemetry.job_id)
        if current is not None:
            if telemetry.generation < current.generation:
                return False
            if telemetry.generation == current.generation and telemetry.run_id != current.run_id:
                return False
        self._by_job[telemetry.job_id] = telemetry
        return True

    def get(self, job_id: str) -> JobTelemetry | None:
        return self._by_job.get(job_id)

    def invalidate_all(self) -> None:
        self._by_job.clear()
