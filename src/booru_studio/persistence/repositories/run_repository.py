from __future__ import annotations

import sqlite3

from booru_studio.common.ids import EnginePackId, JobId, JobRunId
from booru_studio.common.serialization import canonical_json_dumps, json_loads_object
from booru_studio.domain.enums import RunOutcome
from booru_studio.domain.invariants import validate_run
from booru_studio.domain.run import ExecutionSpecSnapshot, JobRun, RuntimePolicy


def _runtime_policy_to_json(policy: RuntimePolicy) -> str:
    return canonical_json_dumps(
        {
            "bandwidth_limit_bps": policy.bandwidth_limit_bps,
            "priority": policy.priority,
            "max_parallel_transfers": policy.max_parallel_transfers,
        }
    )


def _runtime_policy_from_json(raw: str) -> RuntimePolicy:
    obj = json_loads_object(raw)
    return RuntimePolicy(
        bandwidth_limit_bps=(
            int(obj["bandwidth_limit_bps"]) if obj.get("bandwidth_limit_bps") is not None else None
        ),
        priority=int(obj.get("priority", 0)),
        max_parallel_transfers=(
            int(obj["max_parallel_transfers"])
            if obj.get("max_parallel_transfers") is not None
            else None
        ),
    )


def insert_run(connection: sqlite3.Connection, run: JobRun) -> None:
    validate_run(run)
    connection.execute(
        """
        INSERT INTO job_runs(
            run_id, job_id, engine_pack_id, execution_spec_json, runtime_policy_json,
            worker_generation, started_at_utc_ms, ended_at_utc_ms, outcome
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            str(run.run_id),
            str(run.job_id),
            str(run.engine_pack_id),
            canonical_json_dumps(dict(run.execution_spec.values)),
            _runtime_policy_to_json(run.runtime_policy),
            run.worker_generation,
            run.started_at_utc_ms,
            run.ended_at_utc_ms,
            run.outcome.value if run.outcome is not None else None,
        ),
    )


def get_open_run(connection: sqlite3.Connection, job_id: JobId) -> JobRun | None:
    row = connection.execute(
        """
        SELECT run_id, job_id, engine_pack_id, execution_spec_json, runtime_policy_json,
               worker_generation, started_at_utc_ms, ended_at_utc_ms, outcome
        FROM job_runs
        WHERE job_id=? AND ended_at_utc_ms IS NULL
        """,
        (str(job_id),),
    ).fetchone()
    if row is None:
        return None
    run = JobRun(
        run_id=JobRunId.parse(row["run_id"]),
        job_id=JobId.parse(row["job_id"]),
        engine_pack_id=EnginePackId.parse(row["engine_pack_id"]),
        execution_spec=ExecutionSpecSnapshot(json_loads_object(row["execution_spec_json"])),
        runtime_policy=_runtime_policy_from_json(row["runtime_policy_json"]),
        started_at_utc_ms=int(row["started_at_utc_ms"]),
        ended_at_utc_ms=None,
        outcome=None,
        worker_generation=int(row["worker_generation"]),
    )
    validate_run(run)
    return run


def get_run(connection: sqlite3.Connection, run_id: JobRunId) -> JobRun | None:
    row = connection.execute(
        """
        SELECT run_id, job_id, engine_pack_id, execution_spec_json, runtime_policy_json,
               worker_generation, started_at_utc_ms, ended_at_utc_ms, outcome
        FROM job_runs WHERE run_id=?
        """,
        (str(run_id),),
    ).fetchone()
    if row is None:
        return None
    run = JobRun(
        run_id=JobRunId.parse(row["run_id"]),
        job_id=JobId.parse(row["job_id"]),
        engine_pack_id=EnginePackId.parse(row["engine_pack_id"]),
        execution_spec=ExecutionSpecSnapshot(json_loads_object(row["execution_spec_json"])),
        runtime_policy=_runtime_policy_from_json(row["runtime_policy_json"]),
        started_at_utc_ms=int(row["started_at_utc_ms"]),
        ended_at_utc_ms=(int(row["ended_at_utc_ms"]) if row["ended_at_utc_ms"] is not None else None),
        outcome=RunOutcome(row["outcome"]) if row["outcome"] is not None else None,
        worker_generation=int(row["worker_generation"]),
    )
    validate_run(run)
    return run


def settle_run(
    connection: sqlite3.Connection,
    *,
    run_id: JobRunId,
    outcome: RunOutcome,
    now_utc_ms: int,
) -> None:
    cursor = connection.execute(
        """
        UPDATE job_runs
        SET ended_at_utc_ms=?, outcome=?
        WHERE run_id=? AND ended_at_utc_ms IS NULL
        """,
        (now_utc_ms, outcome.value, str(run_id)),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("run is missing or already settled")
