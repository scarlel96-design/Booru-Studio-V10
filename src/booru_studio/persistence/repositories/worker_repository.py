from __future__ import annotations

import sqlite3

from booru_studio.common.ids import CoreInstanceId, EnginePackId, JobId, JobRunId, WorkerSessionId


def insert_worker_session(
    connection: sqlite3.Connection,
    *,
    worker_session_id: WorkerSessionId,
    core_instance_id: CoreInstanceId,
    run_id: JobRunId,
    job_id: JobId,
    engine_pack_id: EnginePackId,
    worker_generation: int,
    expected_pid: int,
    endpoint_name: str,
    now_utc_ms: int,
) -> None:
    connection.execute(
        """
        INSERT INTO worker_sessions(
            worker_session_id,core_instance_id,run_id,job_id,engine_pack_id,worker_generation,
            expected_pid,endpoint_name,state,last_contiguous_tx_seq,opened_at_utc_ms,closed_at_utc_ms
        ) VALUES(?,?,?,?,?,?,?,?, 'OPEN',0,?,NULL)
        """,
        (
            str(worker_session_id), str(core_instance_id), str(run_id), str(job_id),
            str(engine_pack_id), worker_generation, expected_pid, endpoint_name, now_utc_ms,
        ),
    )


def set_worker_session_state(
    connection: sqlite3.Connection,
    *,
    worker_session_id: WorkerSessionId,
    state: str,
    now_utc_ms: int,
) -> None:
    closed = now_utc_ms if state in {"CLOSED", "FAILED"} else None
    cursor = connection.execute(
        """
        UPDATE worker_sessions
        SET state=?, closed_at_utc_ms=COALESCE(?,closed_at_utc_ms)
        WHERE worker_session_id=?
        """,
        (state, closed, str(worker_session_id)),
    )
    if cursor.rowcount != 1:
        raise KeyError("worker session not found")


def get_worker_session(connection: sqlite3.Connection, worker_session_id: WorkerSessionId) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM worker_sessions WHERE worker_session_id=?",
        (str(worker_session_id),),
    ).fetchone()
