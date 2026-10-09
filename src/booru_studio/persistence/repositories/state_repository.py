from __future__ import annotations

import sqlite3


def get_state_revision(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT state_revision FROM state_meta WHERE singleton_id=1"
    ).fetchone()
    if row is None:
        raise RuntimeError("state_meta singleton is missing")
    return int(row["state_revision"])


def bump_state_revision(connection: sqlite3.Connection, *, now_utc_ms: int) -> int:
    cursor = connection.execute(
        """
        UPDATE state_meta
        SET state_revision = state_revision + 1,
            updated_at_utc_ms = ?
        WHERE singleton_id = 1
        """,
        (now_utc_ms,),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("failed to advance state revision")
    return get_state_revision(connection)


def append_domain_event(
    connection: sqlite3.Connection,
    *,
    state_revision: int,
    event_type: str,
    subject_kind: str,
    subject_id: str,
    payload_json: str,
    now_utc_ms: int,
) -> None:
    connection.execute(
        """
        INSERT INTO domain_events(
            state_revision, event_type, subject_kind, subject_id, payload_json, created_at_utc_ms
        ) VALUES(?,?,?,?,?,?)
        """,
        (
            state_revision,
            event_type,
            subject_kind,
            subject_id,
            payload_json,
            now_utc_ms,
        ),
    )
