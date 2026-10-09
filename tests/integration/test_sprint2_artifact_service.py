from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import pytest

from booru_studio.common.clock import ManualClock
from booru_studio.common.ids import ClientInstanceId, CommandId, StorageTargetId
from booru_studio.core.artifact_service import ArtifactService
from booru_studio.core.job_service import JobService
from booru_studio.domain.commands import CommandIdentity, CreateJobCommand
from booru_studio.domain.enums import InputKind, JobKind
from booru_studio.domain.file_commit import FileCommitStrategy, RecoveryDisposition
from booru_studio.persistence.db_actor import DbActor
from booru_studio.worker.resume import read_resume_sidecar, write_resume_sidecar
from booru_studio.worker.staging import perform_commit


def _setup(tmp_path: Path):
    clock = ManualClock(1000, 0)
    actor = DbActor(tmp_path / "상태" / "db.sqlite3", now_utc_ms=clock.utc_ms())
    actor.start()
    jobs = JobService(actor, clock)
    target_id = StorageTargetId.new()
    target_root = tmp_path / "다운로드" / "새 폴더 (6)"
    artifacts = ArtifactService(actor, clock)
    artifacts.register_storage_target(storage_target_id=target_id, generation=1, root=target_root)
    created = jobs.create_job(CreateJobCommand(
        identity=CommandIdentity(ClientInstanceId.new(), CommandId.new()),
        input_kind=InputKind.URL,
        redacted_input="https://example.invalid/file",
        job_kind=JobKind.DIRECT_FILE,
        title="한글 테스트",
        storage_target_id=target_id,
        storage_target_generation=1,
    ))
    return clock, actor, jobs, artifacts, created, target_id, target_root


def _stage(plan, data: bytes) -> bytes:
    plan.staging_path.parent.mkdir(parents=True, exist_ok=True)
    plan.staging_path.write_bytes(data)
    return hashlib.sha256(data).digest()


def test_full_file_commit_round_trip_and_revision(tmp_path: Path) -> None:
    clock, actor, _, svc, created, target_id, root = _setup(tmp_path)
    try:
        data = b"hello-v10" * 100
        digest = hashlib.sha256(data).digest()
        plan = svc.plan_artifact(
            job_id=created.job_id, storage_target_id=target_id, storage_generation=1,
            relative_path="한글/파일.bin", expected_size=len(data), expected_sha256=digest,
        )
        _stage(plan, data)
        grant = svc.prepare_commit(artifact_id=plan.artifact_id)
        result = perform_commit(grant)
        finalized = svc.finalize_commit(result)
        assert plan.final_path.read_bytes() == data
        assert finalized.committed_state_revision == 4
        row = actor.submit(lambda c: c.execute(
            "SELECT lifecycle,filesystem_state,commit_owned FROM artifacts WHERE artifact_id=?",
            (str(plan.artifact_id),),
        ).fetchone()).result(2)
        assert tuple(row) == ("COMMITTED", "PRESENT", 1)
        assert actor.submit(lambda c: c.execute("PRAGMA integrity_check").fetchone()[0]).result(2) == "ok"
    finally:
        actor.close()


def test_final_existing_file_is_never_replaced(tmp_path: Path) -> None:
    _, actor, _, svc, created, target_id, _ = _setup(tmp_path)
    try:
        plan = svc.plan_artifact(job_id=created.job_id, storage_target_id=target_id, storage_generation=1, relative_path="x.bin")
        _stage(plan, b"new")
        plan.final_path.parent.mkdir(parents=True, exist_ok=True)
        plan.final_path.write_bytes(b"foreign")
        with pytest.raises(FileExistsError):
            svc.prepare_commit(artifact_id=plan.artifact_id)
        assert plan.final_path.read_bytes() == b"foreign"
    finally:
        actor.close()

@pytest.mark.parametrize("bad", ["../evil.bin", "/abs.bin", "C:/abs.bin", "CON.txt", "x:ads", "bad?.bin", "trail. "])
def test_unsafe_relative_paths_are_rejected(tmp_path: Path, bad: str) -> None:
    _, actor, _, svc, created, target_id, _ = _setup(tmp_path)
    try:
        with pytest.raises(ValueError):
            svc.plan_artifact(job_id=created.job_id, storage_target_id=target_id, storage_generation=1, relative_path=bad)
    finally:
        actor.close()


def test_case_insensitive_path_claim_collision_rejected(tmp_path: Path) -> None:
    _, actor, _, svc, created, target_id, _ = _setup(tmp_path)
    try:
        svc.plan_artifact(job_id=created.job_id, storage_target_id=target_id, storage_generation=1, relative_path="Folder/File.JPG")
        with pytest.raises(FileExistsError):
            svc.plan_artifact(job_id=created.job_id, storage_target_id=target_id, storage_generation=1, relative_path="folder/file.jpg")
    finally:
        actor.close()


def test_prepare_must_commit_db_before_filesystem_mutation(tmp_path: Path) -> None:
    _, actor, _, svc, created, target_id, _ = _setup(tmp_path)
    try:
        plan = svc.plan_artifact(job_id=created.job_id, storage_target_id=target_id, storage_generation=1, relative_path="x.bin")
        _stage(plan, b"abc")
        grant = svc.prepare_commit(artifact_id=plan.artifact_id)
        row = actor.submit(lambda c: c.execute(
            "SELECT state FROM file_commit_intents WHERE commit_intent_id=?", (str(grant.commit_intent_id),)
        ).fetchone()).result(2)
        assert row[0] == "PREPARED"
        assert not plan.final_path.exists()
        assert plan.staging_path.exists()
    finally:
        actor.close()


def test_recovery_after_prepared_keeps_verified_staging_for_retry(tmp_path: Path) -> None:
    _, actor, _, svc, created, target_id, _ = _setup(tmp_path)
    try:
        plan = svc.plan_artifact(job_id=created.job_id, storage_target_id=target_id, storage_generation=1, relative_path="x.bin")
        _stage(plan, b"abc")
        grant = svc.prepare_commit(artifact_id=plan.artifact_id)
        results = svc.recover_open_commits()
        assert [(r.commit_intent_id, r.disposition) for r in results] == [(grant.commit_intent_id, RecoveryDisposition.RETRY_COMMIT)]
    finally:
        actor.close()


def test_recovery_after_rename_before_db_finalizes(tmp_path: Path) -> None:
    _, actor, _, svc, created, target_id, _ = _setup(tmp_path)
    try:
        data = b"abc" * 100
        plan = svc.plan_artifact(job_id=created.job_id, storage_target_id=target_id, storage_generation=1, relative_path="x.bin")
        _stage(plan, data)
        grant = svc.prepare_commit(artifact_id=plan.artifact_id)
        perform_commit(grant)  # simulate lost result / Core crash before DB finalize
        recovered = svc.recover_open_commits()
        assert recovered[0].disposition is RecoveryDisposition.FINALIZED
        assert plan.final_path.read_bytes() == data
        assert actor.submit(lambda c: c.execute("SELECT COUNT(*) FROM file_records").fetchone()[0]).result(2) == 1
    finally:
        actor.close()


def test_copy_recovery_requires_durable_marker(tmp_path: Path) -> None:
    _, actor, _, svc, created, target_id, _ = _setup(tmp_path)
    try:
        data = b"copy-data"
        plan = svc.plan_artifact(job_id=created.job_id, storage_target_id=target_id, storage_generation=1, relative_path="copy.bin")
        _stage(plan, data)
        grant = svc.prepare_commit(artifact_id=plan.artifact_id, strategy=FileCommitStrategy.COPY_VERIFY_COMMIT)
        perform_commit(grant)
        grant.marker_path.unlink()
        recovered = svc.recover_open_commits()
        assert recovered[0].disposition is RecoveryDisposition.REVIEW_REQUIRED
        assert plan.final_path.read_bytes() == data
        assert actor.submit(lambda c: c.execute("SELECT COUNT(*) FROM file_records").fetchone()[0]).result(2) == 0
    finally:
        actor.close()


def test_copy_recovery_with_marker_finalizes(tmp_path: Path) -> None:
    _, actor, _, svc, created, target_id, _ = _setup(tmp_path)
    try:
        data = b"copy-data"
        plan = svc.plan_artifact(job_id=created.job_id, storage_target_id=target_id, storage_generation=1, relative_path="copy.bin")
        _stage(plan, data)
        grant = svc.prepare_commit(artifact_id=plan.artifact_id, strategy=FileCommitStrategy.COPY_VERIFY_COMMIT)
        perform_commit(grant)
        recovered = svc.recover_open_commits()
        assert recovered[0].disposition is RecoveryDisposition.FINALIZED
    finally:
        actor.close()


def test_foreign_mismatching_final_is_preserved_for_review(tmp_path: Path) -> None:
    _, actor, _, svc, created, target_id, _ = _setup(tmp_path)
    try:
        plan = svc.plan_artifact(job_id=created.job_id, storage_target_id=target_id, storage_generation=1, relative_path="x.bin")
        _stage(plan, b"ours")
        grant = svc.prepare_commit(artifact_id=plan.artifact_id)
        plan.final_path.parent.mkdir(parents=True, exist_ok=True)
        plan.final_path.write_bytes(b"foreign")
        recovered = svc.recover_open_commits()
        assert recovered[0].disposition is RecoveryDisposition.REVIEW_REQUIRED
        assert plan.final_path.read_bytes() == b"foreign"
    finally:
        actor.close()


def test_missing_staging_and_final_marks_failed_recovery(tmp_path: Path) -> None:
    _, actor, _, svc, created, target_id, _ = _setup(tmp_path)
    try:
        plan = svc.plan_artifact(job_id=created.job_id, storage_target_id=target_id, storage_generation=1, relative_path="x.bin")
        _stage(plan, b"ours")
        svc.prepare_commit(artifact_id=plan.artifact_id)
        plan.staging_path.unlink()
        recovered = svc.recover_open_commits()
        assert recovered[0].disposition is RecoveryDisposition.FAILED
    finally:
        actor.close()


def test_lost_finalize_ack_can_be_replayed_without_duplicate_file_record(tmp_path: Path) -> None:
    _, actor, _, svc, created, target_id, _ = _setup(tmp_path)
    try:
        plan = svc.plan_artifact(job_id=created.job_id, storage_target_id=target_id, storage_generation=1, relative_path="x.bin")
        _stage(plan, b"abc")
        grant = svc.prepare_commit(artifact_id=plan.artifact_id)
        result = perform_commit(grant)
        svc.finalize_commit(result)
        svc.finalize_commit(result)
        assert actor.submit(lambda c: c.execute("SELECT COUNT(*) FROM file_records").fetchone()[0]).result(2) == 1
    finally:
        actor.close()


def test_resume_sidecar_roundtrip_and_core_mirror(tmp_path: Path) -> None:
    _, actor, _, svc, created, target_id, root = _setup(tmp_path)
    try:
        plan = svc.plan_artifact(job_id=created.job_id, storage_target_id=target_id, storage_generation=1, relative_path="x.bin")
        part = plan.staging_path
        _stage(plan, b"partial")
        sidecar = part.with_suffix(part.suffix + ".resume.json")
        state = write_resume_sidecar(
            artifact_id=plan.artifact_id, generation=2, part_path=part, sidecar_path=sidecar,
            source_fingerprint="source-1", validator={"etag": "abc"},
        )
        mirrored = svc.register_resume_sidecar(sidecar)
        assert mirrored.part_size == 7 and state.payload_checksum == mirrored.payload_checksum
        row = actor.submit(lambda c: c.execute(
            "SELECT generation,part_size FROM resume_records WHERE artifact_id=?", (str(plan.artifact_id),)
        ).fetchone()).result(2)
        assert tuple(row) == (2, 7)
    finally:
        actor.close()


def test_resume_sidecar_detects_part_size_change(tmp_path: Path) -> None:
    _, actor, _, svc, created, target_id, _ = _setup(tmp_path)
    try:
        plan = svc.plan_artifact(job_id=created.job_id, storage_target_id=target_id, storage_generation=1, relative_path="x.bin")
        _stage(plan, b"partial")
        sidecar = plan.staging_path.with_suffix(".resume.json")
        write_resume_sidecar(
            artifact_id=plan.artifact_id, generation=1, part_path=plan.staging_path, sidecar_path=sidecar,
            source_fingerprint="s", validator={},
        )
        with plan.staging_path.open("ab") as f: f.write(b"more")
        with pytest.raises(ValueError): read_resume_sidecar(sidecar)
    finally:
        actor.close()


def test_symlink_staging_is_rejected_when_supported(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlink unsupported")
    _, actor, _, svc, created, target_id, _ = _setup(tmp_path)
    try:
        plan = svc.plan_artifact(job_id=created.job_id, storage_target_id=target_id, storage_generation=1, relative_path="x.bin")
        plan.staging_path.parent.mkdir(parents=True, exist_ok=True)
        real = tmp_path / "real.bin"; real.write_bytes(b"abc")
        try: plan.staging_path.symlink_to(real)
        except OSError: pytest.skip("symlink creation denied")
        with pytest.raises(ValueError): svc.prepare_commit(artifact_id=plan.artifact_id)
    finally:
        actor.close()
