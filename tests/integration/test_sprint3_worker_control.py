from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from booru_studio.common.clock import ManualClock
from booru_studio.common.ids import ClientInstanceId, CommandId, EnginePackId
from booru_studio.core.job_service import JobService
from booru_studio.core.worker_launcher import WorkerLauncher
from booru_studio.core.worker_protocol import CoreWorkerController
from booru_studio.domain.commands import (
    CancelJobCommand, CommandIdentity, CreateJobCommand, StartJobRunRequest,
)
from booru_studio.domain.enums import ControlIntent, InputKind, JobKind
from booru_studio.domain.run import ExecutionSpecSnapshot, RuntimePolicy
from booru_studio.persistence.db_actor import DbActor
from booru_studio.persistence.transactions.worker_transactions import (
    WorkerTransactionConflict, WorkerTransactionGap, commit_worker_transaction,
)


def _running_job(tmp_path: Path):
    clock = ManualClock(1000, 0)
    actor = DbActor(tmp_path / "한글상태" / "db.sqlite3", now_utc_ms=clock.utc_ms()); actor.start()
    jobs = JobService(actor, clock)
    created = jobs.create_job(CreateJobCommand(
        identity=CommandIdentity(ClientInstanceId.new(), CommandId.new()), input_kind=InputKind.URL,
        redacted_input="https://example.invalid", job_kind=JobKind.DIRECT_FILE, title="워커 테스트",
    ))
    pack = EnginePackId.new()
    run = jobs.start_job_run(StartJobRunRequest(
        job_id=created.job_id, engine_pack_id=pack, execution_spec=ExecutionSpecSnapshot({}),
        runtime_policy=RuntimePolicy(), worker_generation=1,
    ))
    return clock, actor, jobs, created, run, pack


def test_durable_cancel_command_is_idempotent(tmp_path: Path) -> None:
    clock, actor, jobs, created, run, pack = _running_job(tmp_path)
    try:
        cmd = CancelJobCommand(CommandIdentity(ClientInstanceId.new(), CommandId.new()), created.job_id)
        first = jobs.cancel_job(cmd); second = jobs.cancel_job(cmd)
        assert first.replayed is False and second.replayed is True
        assert first.committed_state_revision == second.committed_state_revision == 3
        assert jobs.get_job(created.job_id).control_intent is ControlIntent.CANCEL_REQUESTED
        assert jobs.state_revision() == 3
    finally: actor.close()


def test_worker_transaction_replay_gap_conflict_and_rollback(tmp_path: Path) -> None:
    clock, actor, jobs, created, run, pack = _running_job(tmp_path)
    launcher = WorkerLauncher(actor, clock)
    proc = launcher.spawn_source_stdio(run_id=run.run_id, job_id=created.job_id, engine_pack_id=pack, worker_generation=1)
    try:
        session = proc.packet.worker_session_id
        # Kill harness Worker; this test exercises DB lane directly.
        proc.process.kill(); proc.process.wait(timeout=5)
        ack1 = actor.submit(lambda c: commit_worker_transaction(
            c, worker_session_id=session, tx_seq=1, tx_type="X", payload={"a": 1}, now_utc_ms=clock.utc_ms()
        )).result(2)
        assert ack1 == 1
        replay = actor.submit(lambda c: commit_worker_transaction(
            c, worker_session_id=session, tx_seq=1, tx_type="X", payload={"a": 1}, now_utc_ms=clock.utc_ms()
        )).result(2)
        assert replay == 1
        with pytest.raises(WorkerTransactionConflict):
            actor.submit(lambda c: commit_worker_transaction(
                c, worker_session_id=session, tx_seq=1, tx_type="X", payload={"a": 2}, now_utc_ms=clock.utc_ms()
            )).result(2)
        with pytest.raises(WorkerTransactionGap):
            actor.submit(lambda c: commit_worker_transaction(
                c, worker_session_id=session, tx_seq=3, tx_type="X", payload={}, now_utc_ms=clock.utc_ms()
            )).result(2)
        def explode(_): raise RuntimeError("boom")
        with pytest.raises(RuntimeError):
            actor.submit(lambda c: commit_worker_transaction(
                c, worker_session_id=session, tx_seq=2, tx_type="Y", payload={}, now_utc_ms=clock.utc_ms(), side_effect=explode
            )).result(2)
        counts = actor.submit(lambda c: (
            c.execute("SELECT last_contiguous_tx_seq FROM worker_sessions WHERE worker_session_id=?", (str(session),)).fetchone()[0],
            c.execute("SELECT COUNT(*) FROM worker_tx_receipts WHERE worker_session_id=?", (str(session),)).fetchone()[0],
        )).result(2)
        assert counts == (1, 1)
    finally:
        if proc.process.poll() is None: proc.process.kill()
        actor.close()

@pytest.mark.skipif(os.name == "nt", reason="source stdio harness uses POSIX pass_fds; Windows uses later QLocal gate")
def test_real_worker_subprocess_bootstrap_auth_start_cancel_goodbye(tmp_path: Path) -> None:
    clock, actor, jobs, created, run, pack = _running_job(tmp_path)
    launcher = WorkerLauncher(actor, clock)
    proc = launcher.spawn_source_stdio(run_id=run.run_id, job_id=created.job_id, engine_pack_id=pack, worker_generation=1)
    controller = CoreWorkerController(actor, clock)
    try:
        secret_hex = proc.packet.secret.hex()
        assert secret_hex not in " ".join(str(x) for x in proc.process.args)
        assert proc.packet.secret.hex() not in str(proc.process.args)
        controller.authenticate(proc.connection, proc.packet)
        assert controller.start_run(proc.connection, proc.packet) == 1
        cancel = CancelJobCommand(CommandIdentity(ClientInstanceId.new(), CommandId.new()), created.job_id)
        jobs.cancel_job(cancel)
        assert controller.cancel_run(proc.connection, proc.packet) == 2
        assert proc.process.wait(timeout=5) == 0
        row = actor.submit(lambda c: c.execute(
            "SELECT state,last_contiguous_tx_seq FROM worker_sessions WHERE worker_session_id=?", (str(proc.packet.worker_session_id),)
        ).fetchone()).result(2)
        assert tuple(row) == ("CLOSED", 2)
        assert actor.submit(lambda c: c.execute(
            "SELECT COUNT(*) FROM worker_tx_receipts WHERE worker_session_id=?", (str(proc.packet.worker_session_id),)
        ).fetchone()[0]).result(2) == 2
    finally:
        if proc.process.poll() is None: proc.process.kill()
        actor.close()

@pytest.mark.skipif(os.name == "nt", reason="source stdio harness uses POSIX pass_fds")
def test_ten_sequential_real_worker_lifecycles_leave_no_open_sessions(tmp_path: Path) -> None:
    clock, actor, jobs, created, run, pack = _running_job(tmp_path)
    try:
        # Reuse the same JobRun with distinct generations cannot satisfy schema UNIQUE(run,generation)
        # if generation repeats, so run ten sessions with generation 1..10.
        for generation in range(1, 11):
            launcher = WorkerLauncher(actor, clock)
            proc = launcher.spawn_source_stdio(run_id=run.run_id, job_id=created.job_id, engine_pack_id=pack, worker_generation=generation)
            controller = CoreWorkerController(actor, clock)
            controller.authenticate(proc.connection, proc.packet)
            controller.start_run(proc.connection, proc.packet)
            controller.cancel_run(proc.connection, proc.packet)
            assert proc.process.wait(timeout=5) == 0
        counts = actor.submit(lambda c: (
            c.execute("SELECT COUNT(*) FROM worker_sessions WHERE state='CLOSED'").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM worker_tx_receipts").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM worker_sessions WHERE state<>'CLOSED'").fetchone()[0],
            c.execute("PRAGMA integrity_check").fetchone()[0],
        )).result(2)
        assert counts == (10, 20, 0, "ok")
    finally: actor.close()
