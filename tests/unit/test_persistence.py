from __future__ import annotations

import sqlite3

import pytest
from pathlib import Path

from booru_studio.persistence.db_actor import DbActor
from booru_studio.persistence.schema import APPLICATION_ID, SCHEMA_VERSION, initialize_schema


def test_schema_initializes_strict_tables(tmp_path: Path) -> None:
    path = tmp_path / "상태 데이터베이스.sqlite3"
    connection = sqlite3.connect(path)
    initialize_schema(connection, now_utc_ms=123)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
    assert connection.execute(
        "SELECT state_revision FROM state_meta WHERE singleton_id=1"
    ).fetchone() == (0,)

    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = {
        "jobs",
        "job_runs",
        "items",
        "artifacts",
        "path_claims",
        "file_commit_intents",
        "command_receipts",
        "recovery_episodes",
        "cleanup_obligations",
    }
    assert required <= tables
    connection.close()


def test_db_actor_owns_connection_and_executes_serial_tasks(tmp_path: Path) -> None:
    actor = DbActor(tmp_path / "db.sqlite3", now_utc_ms=1, max_pending=4)
    actor.start()
    try:
        future = actor.submit(lambda connection: connection.execute("SELECT state_revision FROM state_meta").fetchone()[0])
        assert future.result(timeout=2) == 0
    finally:
        actor.close()


def test_storage_target_generation_is_referentially_pinned(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "storage.sqlite3")
    initialize_schema(connection, now_utc_ms=1)
    connection.execute(
        "INSERT INTO submissions(submission_id,input_kind,redacted_input,created_at_utc_ms) VALUES(?,?,?,?)",
        ("s1", "URL", "https://example.invalid", 1),
    )
    connection.execute(
        "INSERT INTO storage_targets(storage_target_id,generation,kind,normalized_root,identity_json,capability_json,created_at_utc_ms) VALUES(?,?,?,?,?,?,?)",
        ("target", 3, "LOCAL", "D:/Downloads", "{}", "{}", 1),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT INTO jobs(
                job_id,submission_id,kind,title,lifecycle,outcome,control_intent,activities_json,
                waiting_reasons_json,storage_target_id,storage_target_generation,priority,
                created_at_utc_ms,updated_at_utc_ms
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "j1", "s1", "DIRECT_FILE", "fixture", "QUEUED", None, "NONE", "[]", "[]",
                "target", 4, 0, 1, 1,
            ),
        )
    connection.close()
