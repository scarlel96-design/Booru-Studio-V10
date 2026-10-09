from __future__ import annotations

import hashlib
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from booru_studio.common.clock import SystemClock
from booru_studio.common.ids import ClientInstanceId, CommandId, StorageTargetId
from booru_studio.common.random_source import DeterministicRandomSource
from booru_studio.core.artifact_service import ArtifactService
from booru_studio.core.job_service import JobService
from booru_studio.domain.commands import CommandIdentity, CreateJobCommand
from booru_studio.domain.enums import InputKind, JobKind
from booru_studio.engine.adapters.direct_http import DirectHttpTransfer, DirectHttpWorker, TransferCancelled
from booru_studio.persistence.db_actor import DbActor
from booru_studio.scheduler.adaptive_network import HostAdaptiveLimiter
from booru_studio.scheduler.coordinator import NetworkAdmissionController, ParallelTransferScheduler
from booru_studio.scheduler.retry import RetryPolicy
from booru_studio.worker.resume import write_resume_sidecar
from booru_studio.worker.staging import perform_commit


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.range_headers: list[str] = []
        self.if_range_headers: list[str] = []
        self.rate_hits = 0
        self.reset_hits = 0

    def enter(self) -> None:
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)

    def leave(self) -> None:
        with self.lock:
            self.active -= 1


PARALLEL_BODY = b"p" * (64 * 1024)
RANGE_BODY = bytes(range(256)) * (16 * 1024)  # 4 MiB
CHANGED_BODY = b"new-source" * (256 * 1024)
RESET_BODY = b"reset-recovered" * 8192


class _TestHTTPServer(ThreadingHTTPServer):
    # The stdlib TCPServer default listen backlog is intentionally small and can
    # make a ten-client concurrency test observe only 7-8 server handlers even
    # when the scheduler has correctly admitted ten transfers.  Keep the
    # fixture, rather than the OS listen backlog, as the measured bottleneck.
    request_queue_size = 64
    daemon_threads = True


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: _State

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _send_bytes(self, body: bytes, *, status: int = 200, etag: str = '"v1"', extra=None) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("ETag", etag)
        self.send_header("Last-Modified", "Wed, 21 Oct 2015 07:28:00 GMT")
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path.startswith("/parallel/"):
            self.state.enter()
            try:
                time.sleep(0.35)
                self._send_bytes(PARALLEL_BODY)
            finally:
                self.state.leave()
            return

        if path == "/range":
            range_header = self.headers.get("Range", "")
            if_range = self.headers.get("If-Range", "")
            if range_header:
                self.state.range_headers.append(range_header)
                self.state.if_range_headers.append(if_range)
            if range_header.startswith("bytes=") and if_range == '"v1"':
                start = int(range_header.removeprefix("bytes=").removesuffix("-"))
                body = RANGE_BODY[start:]
                self._send_bytes(
                    body,
                    status=206,
                    extra={"Content-Range": f"bytes {start}-{len(RANGE_BODY)-1}/{len(RANGE_BODY)}"},
                )
            else:
                self._send_bytes(RANGE_BODY)
            return

        if path == "/changed":
            range_header = self.headers.get("Range", "")
            if range_header:
                self.state.range_headers.append(range_header)
                self.state.if_range_headers.append(self.headers.get("If-Range", ""))
            # Old validator deliberately causes a full 200 representation.
            self._send_bytes(CHANGED_BODY, etag='"v2"')
            return

        if path == "/rate":
            with self.state.lock:
                self.state.rate_hits += 1
                hit = self.state.rate_hits
            if hit == 1:
                self.send_response(429)
                self.send_header("Retry-After", "0")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._send_bytes(b"rate-ok")
            return

        if path == "/reset":
            with self.state.lock:
                self.state.reset_hits += 1
                hit = self.state.reset_hits
            if hit == 1:
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.connection.close()
                return
            self._send_bytes(RESET_BODY)
            return

        if path == "/slow":
            body = b"s" * (8 * 1024 * 1024)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("ETag", '"slow"')
            self.end_headers()
            for offset in range(0, len(body), 64 * 1024):
                self.wfile.write(body[offset:offset + 64 * 1024]); self.wfile.flush()
                time.sleep(0.01)
            return

        self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()


@pytest.fixture
def http_server():
    state = _State()
    handler = type("Handler", (_Handler,), {"state": state})
    server = _TestHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown(); server.server_close(); thread.join(2)


def _setup(tmp_path: Path):
    clock = SystemClock()
    actor = DbActor(tmp_path / "상태" / "db.sqlite3", now_utc_ms=clock.utc_ms()); actor.start()
    jobs = JobService(actor, clock)
    target_id = StorageTargetId.new()
    root = tmp_path / "다운로드" / "새 폴더 (6)"
    artifacts = ArtifactService(actor, clock)
    artifacts.register_storage_target(storage_target_id=target_id, generation=1, root=root)
    created = jobs.create_job(CreateJobCommand(
        identity=CommandIdentity(ClientInstanceId.new(), CommandId.new()),
        input_kind=InputKind.URL,
        redacted_input="http://127.0.0.1/test",
        job_kind=JobKind.DIRECT_FILE,
        title="Sprint 4",
        storage_target_id=target_id,
        storage_target_generation=1,
    ))
    return actor, artifacts, created.job_id, target_id, root


def _worker_factory():
    return DirectHttpWorker(random_source=DeterministicRandomSource(7))


def _transfer(plan, url: str, body: bytes, *, retries: int = 2, checkpoint_bytes: int = 256 * 1024):
    return DirectHttpTransfer(
        artifact_id=plan.artifact_id,
        generation=1,
        url=url,
        staging_path=plan.staging_path,
        sidecar_path=plan.staging_path.with_suffix(plan.staging_path.suffix + ".resume.json"),
        source_fingerprint=hashlib.sha256(url.encode()).hexdigest(),
        expected_size=len(body),
        expected_sha256=hashlib.sha256(body).digest(),
        retry_policy=RetryPolicy(hard_ceiling=retries, base_delay_s=0.01, max_delay_s=0.05, jitter_s=0),
        timeout_s=5.0,
        checkpoint_bytes=checkpoint_bytes,
        checkpoint_interval_s=0.05,
    )


def test_true_parallel_direct_http_and_crash_safe_commit(tmp_path: Path, http_server) -> None:
    base, server_state = http_server
    actor, artifacts, job_id, target_id, _ = _setup(tmp_path)
    admission = NetworkAdmissionController(
        10,
        host_limiter=HostAdaptiveLimiter(10, minimum=2),
    )
    scheduler = ParallelTransferScheduler(10, worker_factory=_worker_factory, admission=admission)
    try:
        transfers = []
        plans = []
        for index in range(20):
            plan = artifacts.plan_artifact(
                job_id=job_id,
                storage_target_id=target_id,
                storage_generation=1,
                relative_path=f"병렬/{index:03d}.bin",
                expected_size=len(PARALLEL_BODY),
                expected_sha256=hashlib.sha256(PARALLEL_BODY).digest(),
            )
            plans.append(plan)
            transfers.append(_transfer(plan, f"{base}/parallel/{index}", PARALLEL_BODY))
        start = time.monotonic()
        futures = [scheduler.submit(task) for task in transfers]
        results = [future.result(timeout=10) for future in futures]
        elapsed = time.monotonic() - start
        assert len(results) == 20
        assert server_state.peak >= 9
        snap = admission.snapshot()
        assert 9 <= snap.peak <= 10
        assert elapsed < 2.5, f"parallel transfer unexpectedly slow: {elapsed:.3f}s"

        # Integrate the network execution result with the already-proven Sprint 2 commit boundary.
        for plan, result in zip(plans, results, strict=True):
            assert result.sha256 == hashlib.sha256(PARALLEL_BODY).digest()
            artifacts.register_resume_sidecar(result.sidecar_path)
            grant = artifacts.prepare_commit(artifact_id=plan.artifact_id)
            committed = perform_commit(grant)
            artifacts.finalize_commit(committed)
        counts = actor.submit(lambda c: (
            c.execute("SELECT COUNT(*) FROM artifacts WHERE lifecycle='COMMITTED'").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM file_records").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM file_commit_intents WHERE state<>'COMMITTED'").fetchone()[0],
            c.execute("PRAGMA integrity_check").fetchone()[0],
        )).result(3)
        assert counts == (20, 20, 0, "ok")
    finally:
        scheduler.close()
        actor.close()


def test_range_if_range_resume_reuses_checkpoint(tmp_path: Path, http_server) -> None:
    base, state = http_server
    actor, artifacts, job_id, target_id, _ = _setup(tmp_path)
    scheduler = ParallelTransferScheduler(2, worker_factory=_worker_factory)
    try:
        plan = artifacts.plan_artifact(
            job_id=job_id, storage_target_id=target_id, storage_generation=1,
            relative_path="이어받기/파일.bin", expected_size=len(RANGE_BODY),
            expected_sha256=hashlib.sha256(RANGE_BODY).digest(),
        )
        task = _transfer(plan, f"{base}/range", RANGE_BODY)
        first = 1024 * 1024
        plan.staging_path.parent.mkdir(parents=True, exist_ok=True)
        plan.staging_path.write_bytes(RANGE_BODY[:first])
        write_resume_sidecar(
            artifact_id=plan.artifact_id, generation=1,
            part_path=plan.staging_path, sidecar_path=task.sidecar_path,
            source_fingerprint=task.source_fingerprint,
            validator={"if_range": '"v1"', "etag": '"v1"', "last_modified": "", "total": len(RANGE_BODY)},
        )
        result = scheduler.submit(task).result(timeout=10)
        assert result.resumed_from == first
        assert state.range_headers == [f"bytes={first}-"]
        assert state.if_range_headers == ['"v1"']
        assert plan.staging_path.read_bytes() == RANGE_BODY
        assert result.sha256 == hashlib.sha256(RANGE_BODY).digest()
    finally:
        scheduler.close(); actor.close()


def test_if_range_mismatch_200_overwrites_stale_partial(tmp_path: Path, http_server) -> None:
    base, state = http_server
    actor, artifacts, job_id, target_id, _ = _setup(tmp_path)
    scheduler = ParallelTransferScheduler(1, worker_factory=_worker_factory)
    try:
        plan = artifacts.plan_artifact(
            job_id=job_id, storage_target_id=target_id, storage_generation=1,
            relative_path="변경/파일.bin", expected_size=len(CHANGED_BODY),
            expected_sha256=hashlib.sha256(CHANGED_BODY).digest(),
        )
        task = _transfer(plan, f"{base}/changed", CHANGED_BODY)
        stale = b"old" * 10000
        plan.staging_path.parent.mkdir(parents=True, exist_ok=True); plan.staging_path.write_bytes(stale)
        write_resume_sidecar(
            artifact_id=plan.artifact_id, generation=1, part_path=plan.staging_path,
            sidecar_path=task.sidecar_path, source_fingerprint=task.source_fingerprint,
            validator={"if_range": '"old"', "etag": '"old"', "last_modified": "", "total": 123456},
        )
        result = scheduler.submit(task).result(timeout=10)
        assert result.resumed_from == 0
        assert state.range_headers == [f"bytes={len(stale)}-"]
        assert plan.staging_path.read_bytes() == CHANGED_BODY
    finally:
        scheduler.close(); actor.close()


def test_429_retry_after_is_bounded_and_does_not_break_transfer(tmp_path: Path, http_server) -> None:
    base, state = http_server
    actor, artifacts, job_id, target_id, _ = _setup(tmp_path)
    scheduler = ParallelTransferScheduler(1, worker_factory=_worker_factory)
    try:
        body = b"rate-ok"
        plan = artifacts.plan_artifact(
            job_id=job_id, storage_target_id=target_id, storage_generation=1,
            relative_path="rate.bin", expected_size=len(body), expected_sha256=hashlib.sha256(body).digest(),
        )
        result = scheduler.submit(_transfer(plan, f"{base}/rate", body, retries=2)).result(timeout=5)
        assert result.attempts == 2
        assert state.rate_hits == 2
    finally:
        scheduler.close(); actor.close()


def test_transport_reset_retries_and_adaptive_limiter_observes_failure(tmp_path: Path, http_server) -> None:
    base, state = http_server
    actor, artifacts, job_id, target_id, _ = _setup(tmp_path)
    limiter = HostAdaptiveLimiter(4, minimum=2)
    admission = NetworkAdmissionController(4, host_limiter=limiter)
    scheduler = ParallelTransferScheduler(1, worker_factory=_worker_factory, admission=admission)
    try:
        plan = artifacts.plan_artifact(
            job_id=job_id, storage_target_id=target_id, storage_generation=1,
            relative_path="reset.bin", expected_size=len(RESET_BODY), expected_sha256=hashlib.sha256(RESET_BODY).digest(),
        )
        result = scheduler.submit(_transfer(plan, f"{base}/reset", RESET_BODY, retries=2)).result(timeout=5)
        assert result.attempts == 2
        assert state.reset_hits == 2
        host_state = limiter.snapshot(base)
        assert host_state.fail_streak >= 1
    finally:
        scheduler.close()…1158 tokens truncated…   )
        elapsed = time.monotonic() - start
        assert len(outcome.finalized) == 8
        assert int(outcome.summary["configured_parallelism"]) == 4
        assert 4 <= int(outcome.summary["peak_network_active"]) <= 4
        assert proc.process.wait(timeout=5) == 0
        assert server_state.peak >= 4
        assert elapsed < 3.0
        assert all(plan.final_path.read_bytes() == PARALLEL_BODY for plan in plans)
        counts = actor.submit(lambda c: (
            c.execute("SELECT COUNT(*) FROM artifacts WHERE lifecycle='COMMITTED'").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM file_records").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM resume_records").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM worker_sessions WHERE state='CLOSED'").fetchone()[0],
            c.execute("PRAGMA integrity_check").fetchone()[0],
        )).result(3)
        assert counts == (8, 8, 0, 1, "ok")
    finally:
        if proc.process.poll() is None:
            proc.process.kill()
        actor.close()


@pytest.mark.skipif(__import__("os").name == "nt", reason="source stdio harness uses POSIX pass_fds")
def test_real_worker_control_plane_cancels_blocking_direct_http_execution(tmp_path: Path, http_server) -> None:
    from booru_studio.common.ids import EnginePackId
    from booru_studio.core.worker_launcher import WorkerLauncher
    from booru_studio.core.worker_protocol import CoreWorkerController
    from booru_studio.domain.commands import StartJobRunRequest
    from booru_studio.domain.run import ExecutionSpecSnapshot, RuntimePolicy
    from booru_studio.ipc.core_worker_protocol import CoreWorkerMessage, make_envelope

    base, _ = http_server
    actor, artifacts, job_id, target_id, _ = _setup(tmp_path)
    jobs = JobService(actor, SystemClock())
    pack = EnginePackId.new()
    run = jobs.start_job_run(StartJobRunRequest(
        job_id=job_id, engine_pack_id=pack, execution_spec=ExecutionSpecSnapshot({}),
        runtime_policy=RuntimePolicy(), worker_generation=1,
    ))
    plan = artifacts.plan_artifact(
        job_id=job_id, storage_target_id=target_id, storage_generation=1,
        relative_path="worker-cancel/slow.bin", expected_size=8 * 1024 * 1024,
    )
    url = f"{base}/slow"
    execution_plan = {
        "mode": "DIRECT_HTTP",
        "parallelism": 1,
        "transfers": [{
            "artifact_id": str(plan.artifact_id), "generation": 1, "url": url,
            "staging_path": str(plan.staging_path),
            "sidecar_path": str(plan.staging_path.with_suffix(plan.staging_path.suffix + ".resume.json")),
            "source_fingerprint": hashlib.sha256(url.encode()).hexdigest(),
            "expected_size": 8 * 1024 * 1024,
            "retry_ceiling": 0,
            "checkpoint_bytes": 64 * 1024,
            "checkpoint_interval_s": 0.01,
        }],
    }
    launcher = WorkerLauncher(actor, SystemClock())
    proc = launcher.spawn_source_stdio(
        run_id=run.run_id, job_id=job_id, engine_pack_id=pack, worker_generation=1
    )
    controller = CoreWorkerController(actor, SystemClock())
    try:
        controller.authenticate(proc.connection, proc.packet)
        proc.connection.send(make_envelope(
            CoreWorkerMessage.START_RUN,
            message_id="start-run-cancel-test",
            payload={
                "run_id": str(run.run_id), "job_id": str(job_id), "worker_generation": 1,
                "execution_plan": execution_plan,
            },
        ))
        assert controller.receive_and_commit_worker_tx(proc.connection, proc.packet.worker_session_id) == 1
        time.sleep(0.12)
        assert controller.cancel_run(proc.connection, proc.packet) == 2
        assert proc.process.wait(timeout=5) == 0
        assert not plan.final_path.exists()
        row = actor.submit(lambda c: c.execute(
            "SELECT state,last_contiguous_tx_seq FROM worker_sessions WHERE worker_session_id=?",
            (str(proc.packet.worker_session_id),),
        ).fetchone()).result(2)
        assert tuple(row) == ("CLOSED", 2)
    finally:
        if proc.process.poll() is None:
            proc.process.kill()
        actor.close()


# Sprint 10 production-control closure: durable UI/Core intents are forwarded to the active Worker
# and become authoritative only when the Worker commits an OBSERVED transaction.
@pytest.mark.skipif(__import__("os").name == "nt", reason="source stdio harness uses POSIX pass_fds")
def test_durable_pause_request_reaches_active_worker_and_suspends_run(tmp_path: Path, http_server) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from booru_studio.common.ids import EnginePackId
    from booru_studio.core.worker_launcher import WorkerLauncher
    from booru_studio.core.worker_protocol import CoreWorkerController
    from booru_studio.domain.commands import PauseJobCommand, StartJobRunRequest
    from booru_studio.domain.enums import ControlIntent, JobLifecycle, RunOutcome
    from booru_studio.domain.run import ExecutionSpecSnapshot, RuntimePolicy

    base, _ = http_server
    actor, artifacts, job_id, target_id, _ = _setup(tmp_path)
    jobs = JobService(actor, SystemClock())
    pack = EnginePackId.new()
    run = jobs.start_job_run(StartJobRunRequest(
        job_id=job_id, engine_pack_id=pack, execution_spec=ExecutionSpecSnapshot({}),
        runtime_policy=RuntimePolicy(), worker_generation=1,
    ))
    plan = artifacts.plan_artifact(
        job_id=job_id, storage_target_id=target_id, storage_generation=1,
        relative_path="sprint10-pause/slow.bin", expected_size=8 * 1024 * 1024,
    )
    url = f"{base}/slow"
    execution_plan = {
        "mode": "DIRECT_HTTP", "parallelism": 1,
        "transfers": [{
            "artifact_id": str(plan.artifact_id), "generation": 1, "url": url,
            "staging_path": str(plan.staging_path),
            "sidecar_path": str(plan.staging_path.with_suffix(plan.staging_path.suffix + ".resume.json")),
            "source_fingerprint": hashlib.sha256(url.encode()).hexdigest(),
            "expected_size": 8 * 1024 * 1024, "retry_ceiling": 0,
            "checkpoint_bytes": 64 * 1024, "checkpoint_interval_s": 0.01,
        }],
    }
    proc = WorkerLauncher(actor, SystemClock()).spawn_source_stdio(
        run_id=run.run_id, job_id=job_id, engine_pack_id=pack, worker_generation=1,
    )
    controller = CoreWorkerController(actor, SystemClock())
    try:
        controller.authenticate(proc.connection, proc.packet)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                controller.run_direct_http_plan, proc.connection, proc.packet,
                execution_plan=execution_plan, artifact_service=artifacts,
            )
            time.sleep(0.12)
            jobs.pause_job(PauseJobCommand(
                CommandIdentity(ClientInstanceId.new(), CommandId.new()), job_id
            ))
            outcome = future.result(timeout=8)
        assert outcome.terminal_reason == "paused"
        assert proc.process.wait(timeout=5) == 0
        job = jobs.get_job(job_id)
        closed_run = jobs.get_run(run.run_id)
        assert job is not None and job.lifecycle is JobLifecycle.PAUSED
        assert job.control_intent is ControlIntent.NONE
        assert closed_run is not None and closed_run.outcome is RunOutcome.SUSPENDED
        assert closed_run.ended_at_utc_ms is not None
        assert not plan.final_path.exists()
        counts = actor.submit(lambda c: (
            c.execute("SELECT COUNT(*) FROM worker_tx_receipts WHERE tx_type='PAUSE_OBSERVED'").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM file_records").fetchone()[0],
            c.execute("PRAGMA integrity_check").fetchone()[0],
        )).result(3)
        assert counts == (1, 0, "ok")
    finally:
        if proc.process.poll() is None:
            proc.process.kill()
        actor.close()


@pytest.mark.skipif(__import__("os").name == "nt", reason="source stdio harness uses POSIX pass_fds")
def test_durable_cancel_request_reaches_active_worker_and_settles_cancelled(tmp_path: Path, http_server) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from booru_studio.common.ids import EnginePackId
    from booru_studio.core.worker_launcher import WorkerLauncher
    from booru_studio.core.worker_protocol import CoreWorkerController
    from booru_studio.domain.commands import CancelJobCommand, StartJobRunRequest
    from booru_studio.domain.enums import ControlIntent, JobLifecycle, JobOutcome, RunOutcome
    from booru_studio.domain.run import ExecutionSpecSnapshot, RuntimePolicy

    base, _ = http_server
    actor, artifacts, job_id, target_id, _ = _setup(tmp_path)
    jobs = JobService(actor, SystemClock())
    pack = EnginePackId.new()
    run = jobs.start_job_run(StartJobRunRequest(
        job_id=job_id, engine_pack_id=pack, execution_spec=ExecutionSpecSnapshot({}),
        runtime_policy=RuntimePolicy(), worker_generation=1,
    ))
    plan = artifacts.plan_artifact(
        job_id=job_id, storage_target_id=target_id, storage_generation=1,
        relative_path="sprint10-cancel/slow.bin", expected_size=8 * 1024 * 1024,
    )
    url = f"{base}/slow"
    execution_plan = {
        "mode": "DIRECT_HTTP", "parallelism": 1,
        "transfers": [{
            "artifact_id": str(plan.artifact_id), "generation": 1, "url": url,
            "staging_path": str(plan.staging_path),
            "sidecar_path": str(plan.staging_path.with_suffix(plan.staging_path.suffix + ".resume.json")),
            "source_fingerprint": hashlib.sha256(url.encode()).hexdigest(),
            "expected_size": 8 * 1024 * 1024, "retry_ceiling": 0,
            "checkpoint_bytes": 64 * 1024, "checkpoint_interval_s": 0.01,
        }],
    }
    proc = WorkerLauncher(actor, SystemClock()).spawn_source_stdio(
        run_id=run.run_id, job_id=job_id, engine_pack_id=pack, worker_generation=1,
    )
    controller = CoreWorkerController(actor, SystemClock())
    try:
        controller.authenticate(proc.connection, proc.packet)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                controller.run_direct_http_plan, proc.connection, proc.packet,
                execution_plan=execution_plan, artifact_service=artifacts,
            )
            time.sleep(0.12)
            jobs.cancel_job(CancelJobCommand(
                CommandIdentity(ClientInstanceId.new(), CommandId.new()), job_id
            ))
            outcome = future.result(timeout=8)
        assert outcome.terminal_reason == "cancelled"
        assert proc.process.wait(timeout=5) == 0
        job = jobs.get_job(job_id)
        closed_run = jobs.get_run(run.run_id)
        assert job is not None and job.lifecycle is JobLifecycle.SETTLED
        assert job.outcome is JobOutcome.CANCELLED and job.control_intent is ControlIntent.NONE
        assert closed_run is not None and closed_run.outcome is RunOutcome.CANCELLED
        assert closed_run.ended_at_utc_ms is not None
        assert not plan.final_path.exists()
        counts = actor.submit(lambda c: (
            c.execute("SELECT COUNT(*) FROM worker_tx_receipts WHERE tx_type='CANCEL_OBSERVED'").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM file_records").fetchone()[0],
            c.execute("PRAGMA integrity_check").fetchone()[0],
        )).result(3)
        assert counts == (1, 0, "ok")
    finally:
        if proc.process.poll() is None:
            proc.process.kill()
        actor.close()


@pytest.mark.skipif(__import__("os").name == "nt", reason="source stdio harness uses POSIX pass_fds")
def test_pause_after_transfer_staged_fences_file_commit_grant(tmp_path: Path, http_server) -> None:
    from booru_studio.common.ids import EnginePackId
    from booru_studio.core.worker_launcher import WorkerLauncher
    from booru_studio.core.worker_protocol import CoreWorkerController
    from booru_studio.domain.commands import PauseJobCommand, StartJobRunRequest
    from booru_studio.domain.enums import JobLifecycle, RunOutcome
    from booru_studio.domain.run import ExecutionSpecSnapshot, RuntimePolicy

    base, _ = http_server
    actor, artifacts, job_id, target_id, _ = _setup(tmp_path)
    jobs = JobService(actor, SystemClock())
    pack = EnginePackId.new()
    run = jobs.start_job_run(StartJobRunRequest(
        job_id=job_id, engine_pack_id=pack, execution_spec=ExecutionSpecSnapshot({}),
        runtime_policy=RuntimePolicy(), worker_generation=1,
    ))
    digest = hashlib.sha256(PARALLEL_BODY).digest()
    plan = artifacts.plan_artifact(
        job_id=job_id, storage_target_id=target_id, storage_generation=1,
        relative_path="sprint10-fence/staged.bin", expected_size=len(PARALLEL_BODY),
        expected_sha256=digest,
    )
    url = f"{base}/parallel/commit-fence"
    execution_plan = {
        "mode": "DIRECT_HTTP", "parallelism": 1,
        "transfers": [{
            "artifact_id": str(plan.artifact_id), "generation": 1, "url": url,
            "staging_path": str(plan.staging_path),
            "sidecar_path": str(plan.staging_path.with_suffix(plan.staging_path.suffix + ".resume.json")),
            "source_fingerprint": hashlib.sha256(url.encode()).hexdigest(),
            "expected_size": len(PARALLEL_BODY), "expected_sha256": digest.hex(),
            "retry_ceiling": 0, "checkpoint_bytes": 16 * 1024, "checkpoint_interval_s": 0.01,
        }],
    }

    class _PauseOnCheckpoint:
        def __init__(self, delegate):
            self._delegate = delegate
            self._done = False
        def __getattr__(self, name):
            return getattr(self._delegate, name)
        def register_resume_sidecar(self, path):
            state = self._delegate.register_resume_sidecar(path)
            if not self._done:
                self._done = True
                jobs.pause_job(PauseJobCommand(
                    CommandIdentity(ClientInstanceId.new(), CommandId.new()), job_id
                ))
            return state

    proc = WorkerLauncher(actor, SystemClock()).spawn_source_stdio(
        run_id=run.run_id, job_id=job_id, engine_pack_id=pack, worker_generation=1,
    )
    controller = CoreWorkerController(actor, SystemClock())
    try:
        controller.authenticate(proc.connection, proc.packet)
        outcome = controller.run_direct_http_plan(
            proc.connection, proc.packet, execution_plan=execution_plan,
            artifact_service=_PauseOnCheckpoint(artifacts),
        )
        assert outcome.terminal_reason == "paused"
        assert proc.process.wait(timeout=5) == 0
        job = jobs.get_job(job_id)
        closed_run = jobs.get_run(run.run_id)
        assert job is not None and job.lifecycle is JobLifecycle.PAUSED
        assert closed_run is not None and closed_run.outcome is RunOutcome.SUSPENDED
        assert plan.staging_path.exists()
        assert not plan.final_path.exists()
        counts = actor.submit(lambda c: (
            c.execute("SELECT COUNT(*) FROM file_commit_intents").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM file_records").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM resume_records").fetchone()[0],
            c.execute("PRAGMA integrity_check").fetchone()[0],
        )).result(3)
        assert counts == (0, 0, 1, "ok")
    finally:
        if proc.process.poll() is None:
            proc.process.kill()
        actor.close()
