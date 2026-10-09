from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from booru_studio.common.clock import ManualClock
from booru_studio.common.ids import ClientInstanceId, CommandId, EnginePackId, StorageTargetId
from booru_studio.core.job_service import JobService
from booru_studio.domain.commands import CommandIdentity, CreateJobCommand, StartJobRunRequest
from booru_studio.domain.enums import InputKind, JobKind, JobLifecycle
from booru_studio.domain.run import ExecutionSpecSnapshot, RuntimePolicy
from booru_studio.persistence.db_actor import DbActor
from booru_studio.persistence.schema import initialize_schema
from booru_studio.persistence.transactions.job_transactions import (
    CommandReplayConflict,
    JobRunConflict,
)


def _command(
    *,
    client: ClientInstanceId,
    command_id: CommandId,
    title: str = "테스트 다운로드",
    redacted_input: str = "https://example.invalid/media",
) -> CreateJobCommand:
    return CreateJobCommand(
        identity=CommandIdentity(client_instance_id=client, command_id=command_id),
        input_kind=InputKind.URL,
        redacted_input=redacted_input,
        job_kind=JobKind.DIRECT_FILE,
        title=title,
        priority=3,
    )


def _service(path: Path, clock: ManualClock) -> tuple[DbActor, JobService]:
    actor = DbActor(path, now_utc_ms=clock.utc_ms())
    actor.start()
    return actor, JobService(actor, clock)


def test_create_job_is_durable_across_actor_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "상태" / "booru.sqlite3"
    clock = ManualClock(1_000, 100)
    client = ClientInstanceId.new()
    command_id = CommandId.new()

    actor, service = _service(db_path, clock)
    first = service.create_job(_command(client=client, command_id=command_id))
    assert first.replayed is False
    assert first.committed_state_revision == 1
    assert service.state_revision() == 1
    queue = service.list_queue()
    assert [(q.job_id, q.position, q.title) for q in queue] == [
        (first.job_id, 1, "테스트 다운로드")
    ]
    actor.close()

    clock.advance(5_000)
    actor2, service2 = _service(db_path, clock)
    try:
        job = service2.get_job(first.job_id)
        assert job is not None
        assert job.lifecycle is JobLifecycle.QUEUED
        assert job.title == "테스트 다운로드"
        assert [entry.job_id for entry in service2.list_queue()] == [first.job_id]
        assert service2.state_revision() == 1
    finally:
        actor2.close()


def test_duplicate_create_command_replays_without_duplicate_job_or_revision(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite3"
    clock = ManualClock(10_000, 0)
    client = ClientInstanceId.new()
    command_id = CommandId.new()
    command = _command(client=client, command_id=command_id)

    actor, service = _service(db_path, clock)
    first = service.create_job(command)
    clock.advance(1_000)
    replay = service.create_job(command)
    assert replay.replayed is True
    assert replay.job_id == first.job_id
    assert replay.submission_id == first.submission_id
    assert replay.committed_state_revision == first.committed_state_revision == 1
    assert service.state_revision() == 1
    assert [row.job_id for row in service.list_queue()] == [first.job_id]
    actor.close()

    actor2, service2 = _service(db_path, clock)
    try:
        replay2 = service2.create_job(command)
        assert replay2.replayed is True
        assert replay2.job_id == first.job_id
        assert service2.state_revision() == 1
        assert len(service2.list_queue()) == 1
    finally:
        actor2.close()


def test_same_command_id_with_changed_payload_is_rejected(tmp_path: Path) -> None:
    clock = ManualClock(1, 1)
    actor, service = _service(tmp_path / "db.sqlite3", clock)
    client = ClientInstanceId.new()
    command_id = CommandId.new()
    try:
        service.create_job(_command(client=client, command_id=command_id, title="A"))
        with pytest.raises(CommandReplayConflict):
            service.create_job(_command(client=client, command_id=command_id, title="B"))
        assert service.state_revision() == 1
        assert len(service.list_queue()) == 1
    finally:
        actor.close()


def test_start_run_is_atomic_persistent_and_removes_job_from_pending_queue(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite3"
    clock = ManualClock(20_000, 0)
    actor, service = _service(db_path, clock)
    created = service.create_job(
        _command(client=ClientInstanceId.new(), command_id=CommandId.new())
    )
    pack_id = EnginePackId.new()

    clock.advance(500)
    started = service.start_job_run(
        StartJobRunRequest(
            job_id=created.job_id,
            engine_pack_id=pack_id,
            execution_spec=ExecutionSpecSnapshot(
                {"destination": "C:/다운로드/새 폴더 (6)", "quality": "original"}
            ),
            runtime_policy=RuntimePolicy(
                bandwidth_limit_bps=10_000_000,
                priority=7,
                max_parallel_transfers=10,
            ),
            worker_generation=4,
        )
    )
    assert started.committed_state_revision == 2
    assert service.state_revision() == 2
    assert service.list_queue() == []
    job = service.get_job(created.job_id)
    assert job is not None and job.lifecycle is JobLifecycle.ACTIVE
    run = service.get_open_run(created.job_id)
    assert run is not None
    assert run.run_id == started.run_id
    assert run.engine_pack_id == pack_id
    assert run.worker_generation == 4
    assert run.execution_spec.values["destination"] == "C:/다운로드/새 폴더 (6)"
    actor.close()

    actor2, service2 = _service(db_path, clock)
    try:
        run2 = service2.get_run(started.run_id)
        assert run2 is not None
        assert run2.job_id == created.job_id
        assert run2.runtime_policy.max_parallel_transfers == 10
        job2 = service2.get_job(created.job_id)
        assert job2 is not None and job2.lifecycle is JobLifecycle.ACTIVE
        assert service2.list_queue() == []
        assert service2.state_revision() == 2
    finally:
        actor2.close()


def test_second_open_run_for_same_job_is_rejected(tmp_path: Path) -> None:
    clock = ManualClock(100, 0)
    actor, service = _service(tmp_path / "db.sqlite3", clock)
    try:
        created = service.create_job(
            _command(client=ClientInstanceId.new(), command_id=CommandId.new())
        )
        request = StartJobRunRequest(
            job_id=created.job_id,
            engine_pack_id=EnginePackId.new(),
            execution_spec=ExecutionSpecSnapshot({}),
            runtime_policy=RuntimePolicy(),
        )
        service.start_job_run(request)
        with pytest.raises(JobRunConflict):
            service.start_job_run(request)
        assert service.state_revision() == 2
    finally:
        actor.close()


def test_failed_create_with_unknown_storage_generation_rolls_back_receipt_and_revision(
    tmp_path: Path,
) -> None:
    clock = ManualClock(100, 0)
    actor, service = _service(tmp_path / "db.sqlite3", clock)
    command = CreateJobCommand(
        identity=CommandIdentity(ClientInstanceId.new(), CommandId.new()),
        input_kind=InputKind.URL,
        redacted_input="https://example.invalid",
        job_kind=JobKind.DIRECT_FILE,
        title="bad target",
        storage_target_id=StorageTargetId.new(),
        storage_target_generation=99,
    )
    try:
        with pytest.raises(sqlite3.IntegrityError):
            service.create_job(command)
        assert service.state_revision() == 0
        assert service.list_queue() == []
        count = actor.submit(
            lambda connection: connection.execute(
                "SELECT COUNT(*) FROM command_receipts"
            ).fetchone()[0]
        ).result(timeout=2)
        assert count == 0
    finally:
        actor.close()


def test_command_receipt_hash_is_32_bytes(tmp_path: Path) -> None:
    clock = ManualClock(100, 0)
    actor, service = _service(tmp_path / "db.sqlite3", clock)
    try:
        service.create_job(
            _command(client=ClientInstanceId.new(), command_id=CommandId.new())
        )
        length = actor.submit(
            lambda connection: connection.execute(
                "SELECT length(request_hash) FROM command_receipts"
            ).fetchone()[0]
        ).result(timeout=2)
        assert length == 32
    finally:
        actor.close()


def test_schema_enforces_only_one_open_run_per_job(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "db.sqlite3")
    initialize_schema(connection, now_utc_ms=1)
    connection.execute(
        "INSERT INTO submissions(submission_id,input_kind,redacted_input,created_at_utc_ms) VALUES(?,?,?,?)",
        ("s", "URL", "redacted", 1),
    )
    connection.execute(
        """
        INSERT INTO jobs(
            job_id,submission_id,kind,title,lifecycle,outcome,control_intent,activities_json,
            waiting_reasons_json,priority,created_at_utc_ms,updated_at_utc_ms
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        ("j", "s", "DIRECT_FILE", "x", "ACTIVE", None, "NONE", "[]", "[]", 0, 1, 1),
    )
    base = ("j", "pack", "{}", "{}", 0, 1, None, None)
    connection.execute(
        "INSERT INTO job_runs(run_id,job_id,engine_pack_id,execution_spec_json,runtime_policy_json,worker_generation,started_at_utc_ms,ended_at_utc_ms,outcome) VALUES(?,?,?,?,?,?,?,?,?)",
        ("r1", *base),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO job_runs(run_id,job_id,engine_pack_id,execution_spec_json,runtime_policy_json,worker_generation,started_at_utc_ms,ended_at_utc_ms,outcome) VALUES(?,?,?,?,?,?,?,?,?)",
            ("r2", *base),
        )
    connection.close()


def test_many_concurrent_create_commands_are_serialized_without_queue_or_revision_loss(
    tmp_path: Path,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    clock = ManualClock(50_000, 0)
    actor, service = _service(tmp_path / "db.sqlite3", clock)
    client = ClientInstanceId.new()
    commands = [
        _command(
            client=client,
            command_id=CommandId.new(),
            title=f"job-{index:03d}",
            redacted_input=f"https://example.invalid/{index}",
        )
        for index in range(64)
    ]
    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(service.create_job, commands))

        assert len({result.job_id for result in results}) == 64
        assert service.state_revision() == 64
        queue = service.list_queue()
        assert len(queue) == 64
        assert [entry.position for entry in queue] == list(range(1, 65))
        assert len({entry.sort_key for entry in queue}) == 64
        revisions = actor.submit(
            lambda connection: [
                row[0]
                for row in connection.execute(
                    "SELECT state_revision FROM domain_events ORDER BY event_id"
                ).fetchall()
            ]
        ).result(timeout=2)
        assert revisions == list(range(1, 65))
    finally:
        actor.close()


def test_command_idempotency_key_is_scoped_by_client_instance(tmp_path: Path) -> None:
    clock = ManualClock(100, 0)
    actor, service = _service(tmp_path / "db.sqlite3", clock)
    shared_command_id = CommandId.new()
    try:
        first = service.create_job(
            _command(client=ClientInstanceId.new(), command_id=shared_command_id, title="A")
        )
        second = service.create_job(
            _command(client=ClientInstanceId.new(), command_id=shared_command_id, title="B")
        )
        assert first.job_id != second.job_id
        assert service.state_revision() == 2
        assert len(service.list_queue()) == 2
    finally:
        actor.close()
