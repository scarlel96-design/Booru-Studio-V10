from __future__ import annotations

from pathlib import Path

from booru_studio.common.clock import ManualClock
from booru_studio.common.ids import ClientInstanceId, CommandId
from booru_studio.core.job_service import JobService
from booru_studio.core.projection_service import ProjectionService
from booru_studio.domain.commands import CommandIdentity, CreateJobCommand, MoveQueueJobCommand, PauseJobCommand, ResumeJobCommand
from booru_studio.domain.enums import InputKind, JobKind
from booru_studio.persistence.db_actor import DbActor


def _create(service: JobService, client: ClientInstanceId, title: str):
    return service.create_job(CreateJobCommand(
        identity=CommandIdentity(client, CommandId.new()), input_kind=InputKind.URL,
        redacted_input=f"https://example.test/{title}", job_kind=JobKind.UNKNOWN, title=title,
    ))


def test_pause_resume_and_queue_reorder_are_durable_and_idempotent(tmp_path: Path) -> None:
    clock = ManualClock(1_000, 1_000)
    actor = DbActor(tmp_path / "state.sqlite3", now_utc_ms=clock.utc_ms()); actor.start()
    service = JobService(actor, clock)
    client = ClientInstanceId.new()
    try:
        a = _create(service, client, "a")
        clock.advance(1); b = _create(service, client, "b")
        clock.advance(1); c = _create(service, client, "c")
        assert [str(x.job_id) for x in service.list_queue()] == [str(a.job_id), str(b.job_id), str(c.job_id)]

        move_id = CommandId.new()
        move = MoveQueueJobCommand(CommandIdentity(client, move_id), c.job_id, "UP")
        first = service.move_queue_job(move); second = service.move_queue_job(move)
        assert second.replayed and first.committed_state_revision == second.committed_state_revision
        assert [str(x.job_id) for x in service.list_queue()] == [str(a.job_id), str(c.job_id), str(b.job_id)]

        pause_id = CommandId.new()
        pause = PauseJobCommand(CommandIdentity(client, pause_id), c.job_id)
        p1 = service.pause_job(pause); p2 = service.pause_job(pause)
        assert p2.replayed and p1.committed_state_revision == p2.committed_state_revision
        assert service.get_job(c.job_id).lifecycle.value == "PAUSED"
        assert str(c.job_id) not in [str(x.job_id) for x in service.list_queue()]

        clock.advance(1)
        service.resume_job(ResumeJobCommand(CommandIdentity(client, CommandId.new()), c.job_id))
        assert service.get_job(c.job_id).lifecycle.value == "QUEUED"
        # Resuming a paused reservation returns it to the durable tail instead of stealing the active FIFO head.
        assert [str(x.job_id) for x in service.list_queue()] == [str(a.job_id), str(b.job_id), str(c.job_id)]
    finally:
        actor.close()


def test_projection_exposes_local_file_path_without_changing_source_redaction(tmp_path: Path) -> None:
    clock = ManualClock(10_000, 10_000)
    actor = DbActor(tmp_path / "state.sqlite3", now_utc_ms=clock.utc_ms()); actor.start()
    service = JobService(actor, clock); client = ClientInstanceId.new()
    created = _create(service, client, "media")
    try:
        def seed(conn):
            conn.execute("INSERT INTO storage_targets VALUES(?,?,?,?,?,?,?,?)", ("st-1",0,"LOCAL",str(tmp_path),"{}","{}",clock.utc_ms(),clock.utc_ms()))
            conn.execute("INSERT INTO artifacts(artifact_id,job_id,item_id,role,lifecycle,filesystem_state,commit_owned,expected_size,sha256,created_at_utc_ms,updated_at_utc_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?)", ("art-1",str(created.job_id),None,"PRIMARY","COMMITTED","PRESENT",1,3,b"x"*32,clock.utc_ms(),clock.utc_ms()))
            conn.execute("INSERT INTO file_records VALUES(?,?,?,?,?,?,?,?,?,?)", ("fr-1","art-1","st-1",0,"folder/file.bin",3,b"x"*32,"PRESENT",clock.utc_ms(),clock.utc_ms()))
            conn.commit()
        actor.submit(seed).result(2)
        row = ProjectionService(actor).snapshot()["downloads"][0]
        assert Path(row["primary_file_path"]).parts[-2:] == ("folder", "file.bin")
        assert "https://example.test/media" in row["display_input"]
    finally:
        actor.close()
