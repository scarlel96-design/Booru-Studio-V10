from __future__ import annotations

import sqlite3

from booru_studio.common.ids import RetryEpisodeId


def upsert_rate_limit_gate(
    connection: sqlite3.Connection,
    *,
    gate_key: str,
    network_context_key: str,
    deadline_utc_ms: int,
    source: str,
    now_utc_ms: int,
) -> None:
    connection.execute(
        """
        INSERT INTO rate_limit_gates(gate_key,network_context_key,deadline_utc_ms,source,updated_at_utc_ms)
        VALUES(?,?,?,?,?)
        ON CONFLICT(gate_key) DO UPDATE SET
            network_context_key=excluded.network_context_key,
            deadline_utc_ms=max(rate_limit_gates.deadline_utc_ms, excluded.deadline_utc_ms),
            source=excluded.source,
            updated_at_utc_ms=excluded.updated_at_utc_ms
        """,
        (gate_key, network_context_key, deadline_utc_ms, source, now_utc_ms),
    )


def get_rate_limit_deadline(connection: sqlite3.Connection, gate_key: str) -> int | None:
    row = connection.execute(
        "SELECT deadline_utc_ms FROM rate_limit_gates WHERE gate_key=?", (gate_key,)
    ).fetchone()
    return None if row is None else int(row["deadline_utc_ms"])


def delete_rate_limit_gate(connection: sqlite3.Connection, gate_key: str) -> None:
    connection.execute("DELETE FROM rate_limit_gates WHERE gate_key=?", (gate_key,))


def get_open_retry_episode(
    connection: sqlite3.Connection, *, scope_kind: str, scope_id: str, error_code: str
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT * FROM retry_episodes
        WHERE scope_kind=? AND scope_id=? AND error_code=? AND state='OPEN'
        ORDER BY first_failure_at_utc_ms DESC LIMIT 1
        """,
        (scope_kind, scope_id, error_code),
    ).fetchone()


def insert_retry_episode(
    connection: sqlite3.Connection,
    *,
    retry_episode_id: RetryEpisodeId,
    scope_kind: str,
    scope_id: str,
    error_code: str,
    hard_ceiling: int,
    next_retry_at_utc_ms: int | None,
    now_utc_ms: int,
) -> None:
    connection.execute(
        """
        INSERT INTO retry_episodes(
            retry_episode_id,scope_kind,scope_id,error_code,attempt_count,hard_ceiling,state,
            next_retry_at_utc_ms,first_failure_at_utc_ms,last_failure_at_utc_ms
        ) VALUES(?,?,?,?,1,?,'OPEN',?,?,?)
        """,
        (
            str(retry_episode_id), scope_kind, scope_id, error_code, hard_ceiling,
            next_retry_at_utc_ms, now_utc_ms, now_utc_ms,
        ),
    )


def increment_retry_episode(
    connection: sqlite3.Connection,
    *,
    retry_episode_id: RetryEpisodeId,
    next_retry_at_utc_ms: int | None,
    now_utc_ms: int,
) -> tuple[int, int]:
    connection.execute(
        """
        UPDATE retry_episodes
        SET attempt_count=attempt_count+1,next_retry_at_utc_ms=?,last_failure_at_utc_ms=?
        WHERE retry_episode_id=? AND state='OPEN'
        """,
        (next_retry_at_utc_ms, now_utc_ms, str(retry_episode_id)),
    )
    row = connection.execute(
        "SELECT attempt_count,hard_ceiling FROM retry_episodes WHERE retry_episode_id=?",
        (str(retry_episode_id),),
    ).fetchone()
    if row is None:
        raise KeyError("retry episode not found")
    return int(row["attempt_count"]), int(row["hard_ceiling"])


def set_retry_episode_state(
    connection: sqlite3.Connection, *, retry_episode_id: RetryEpisodeId, state: str, now_utc_ms: int
) -> None:
    connection.execute(
        """
        UPDATE retry_episodes SET state=?,last_failure_at_utc_ms=? WHERE retry_episode_id=?
        """,
        (state, now_utc_ms, str(retry_episode_id)),
    )
