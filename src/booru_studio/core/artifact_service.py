from __future__ import annotations

import os
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import TypeVar

from booru_studio.common.clock import Clock
from booru_studio.common.hashing import sha256_file
from booru_studio.common.ids import (
    ArtifactId,
    CommitIntentId,
    FileRecordId,
    JobId,
    ItemId,
    PathClaimId,
    StorageTargetId,
)
from booru_studio.common.paths import normalize_relative_path, reject_symlink, resolve_contained
from booru_studio.common.serialization import canonical_json_dumps
from booru_studio.domain.file_commit import (
    ArtifactPlan,
    CommitGrant,
    CommitResult,
    FileCommitStrategy,
    FinalizeResult,
    RecoveryDisposition,
    RecoveryResult,
    StorageTarget,
)
from booru_studio.domain.resume import ResumeState
from booru_studio.persistence.db_actor import DbActor
from booru_studio.persistence.repositories.artifact_repository import (
    finalize_commit,
    get_commit_row,
    get_open_commit_rows,
    insert_artifact_and_claim,
    insert_storage_target,
    mark_commit_failed,
    mark_commit_uncertain,
    prepare_commit_intent,
)
from booru_studio.persistence.repositories.resume_repository import upsert_resume_record
from booru_studio.persistence.repositories.state_repository import append_domain_event, bump_state_revision
from booru_studio.persistence.transactions.base import write_transaction
from booru_studio.worker.resume import read_resume_sidecar

T = TypeVar("T")


class ArtifactService:
    def __init__(self, db_actor: DbActor, clock: Clock, *, db_timeout_s: float = 5.0) -> None:
        self._db_actor = db_actor
        self._clock = clock
        self._db_timeout_s = db_timeout_s

    def _wait(self, future: Future[T]) -> T:
        try:
            return future.result(timeout=self._db_timeout_s)
        except FutureTimeoutError as exc:
            raise TimeoutError("database operation timed out") from exc

    def register_storage_target(
        self, *, storage_target_id: StorageTargetId, generation: int, root: Path,
        kind: str = "LOCAL", identity_json: str = "{}", capability_json: str = "{}"
    ) -> None:
        if generation < 0:
            raise ValueError("storage target generation cannot be negative")
        root.mkdir(parents=True, exist_ok=True)
        normalized_root = str(root.resolve())
        now = self._clock.utc_ms()
        def op(connection):
            with write_transaction(connection):
                insert_storage_target(
                    connection,
                    storage_target_id=storage_target_id,
                    generation=generation,
                    kind=kind,
                    normalized_root=normalized_root,
                    identity_json=identity_json,
                    capability_json=capability_json,
                    now_utc_ms=now,
                )
        self._wait(self._db_actor.submit(op))

    def plan_artifact(
        self, *, job_id: JobId, storage_target_id: StorageTargetId, storage_generation: int,
        relative_path: str, role: str = "PRIMARY", expected_size: int | None = None,
        expected_sha256: bytes | None = None, item_id: ItemId | None = None,
    ) -> ArtifactPlan:
        if expected_sha256 is not None and len(expected_sha256) != 32:
            raise ValueError("expected SHA-256 must be 32 bytes")
        normalized = normalize_relative_path(relative_path)
        artifact_id = ArtifactId.new()
        claim_id = PathClaimId.new()
        now = self._clock.utc_ms()

        def op(connection):
            row = connection.execute(
                "SELECT normalized_root FROM storage_targets WHERE storage_target_id=? AND generation=?",
                (str(storage_target_id), storage_generation),
            ).fetchone()
            if row is None:
                raise KeyError("storage target generation not found")
            if item_id is not None:
                item_row = connection.execute(
                    "SELECT job_id FROM items WHERE item_id=?", (str(item_id),)
                ).fetchone()
                if item_row is None:
                    raise KeyError("item not found")
                if str(item_row["job_id"]) != str(job_id):
                    raise ValueError("artifact Item belongs to a different Job")
            collision = connection.execute(
                """
                SELECT 1 FROM path_claims
                WHERE storage_target_id=? AND storage_generation=?
                  AND lower(normalized_relative_path)=lower(?)
                  AND state IN ('CLAIMED','COMMITTED','RECOVERY_REQUIRED')
                LIMIT 1
                """,
                (str(storage_target_id), storage_generation, normalized),
            ).fetchone()
            if collision is not None:
                raise FileExistsError("destination path is already claimed")
            with write_transaction(connection):
                insert_artifact_and_claim(
                    connection,
                    artifact_id=artifact_id,
                    path_claim_id=claim_id,
                    job_id=job_id,
                    item_id=item_id,
                    role=role,
                    storage_target_id=storage_target_id,
                    storage_generation=storage_generation,
                    normalized_relative_path=normalized,
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                    now_utc_ms=now,
                )
                revision = bump_state_revision(connection, now_utc_ms=now)
                append_domain_event(
                    connection,
                    state_revision=revision,
                    event_type="ARTIFACT_PLANNED",
                    subject_kind="ARTIFACT",
                    subject_id=str(artifact_id),
                    payload_json=canonical_json_dumps({"path": normalized}),
                    now_utc_ms=now,
                )
                return str(row["normalized_root"])

        root = Path(self._wait(self._db_actor.submit(op)))
        staging_root = root / ".booru-studio" / "staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging = staging_root / f"{artifact_id}.part"
        final_path = resolve_contained(root, normalized)
        return ArtifactPlan(
            artifact_id=artifact_id,
            path_claim_id=claim_id,
            staging_path=staging,
            final_path=final_path,
            normalized_relative_path=normalized,
        )

    def prepare_commit(
        self, *, artifact_id: ArtifactId, strategy: FileCommitStrategy = FileCommitStrategy.ATOMIC_RENAME
    ) -> CommitGrant:
        now = self._clock.utc_ms()
        def load(connection):
            return connection.execute(
                """
                SELECT a.expected_size,a.sha256,p.path_claim_id,p.normalized_relative_path,
                       p.storage_target_id,p.storage_generation,s.normalized_root
                FROM artifacts a
                JOIN path_claims p ON p.artifact_id=a.artifact_id
                JOIN storage_targets s ON s.storage_target_id=p.storage_target_id AND s.generation=p.storage_generation
                WHERE a.artifact_id=?
                """,
                (str(artifact_id),),
            ).fetchone()
        row = self._wait(self._db_actor.submit(load))
        if row is None:
            raise KeyError(f"artifact not found: {artifact_id}")
        root = Path(str(row["normalized_root"]))
        staging = root / ".booru-studio" / "staging" / f"{artifact_id}.part"
        reject_symlink(staging, allow_missing=False)
        if not staging.is_file():
            raise FileNotFoundError(staging)
        actual_size = staging.stat().st_size
        actual_hash = sha256_file(staging)
        expected_size = int(row["expected_size"]) if row["expected_size"] is not None else actual_size
        expected_hash = bytes(row["sha256"]) if row["sha256"] is not None else actual_hash
        if actual_size != expected_size or actual_hash != expected_hash:
            raise ValueError("staging content does not satisfy artifact expectation")
        final_path = resolve_contained(root, str(row["normalized_relative_path"]))
        reject_symlink(final_path)
        if final_path.exists():
            raise FileExistsError(final_path)
        commit_intent_id = CommitIntentId.new()
        path_claim_id = PathClaimId.parse(str(row["path_claim_id"]))

        def op(connection):
            with write_transaction(connection):
                # Re-check no final record and no existing intent under the same durable transaction.
                if connection.execute(
                    "SELECT 1 FROM file_commit_intents WHERE artifact_id=?", (str(artifact_id),)
                ).fetchone() is not None:
                    raise RuntimeError("artifact already has a commit intent")
                prepare_commit_intent(
                    connection,
                    commit_intent_id=commit_intent_id,
                    artifact_id=artifact_id,
                    path_claim_id=path_claim_id,
                    strategy=strategy,
                    staging_path=staging,
                    final_relative_path=str(row["normalized_relative_path"]),
                    expected_size=expected_size,
                    expected_sha256=expected_hash,
                    now_utc_ms=now,
                )
                revision = bump_state_revision(connection, now_utc_ms=now)
                append_domain_event(
                    connection,
                    state_revision=revision,
                    event_type="FILE_COMMIT_PREPARED",
                    subject_kind="ARTIFACT",
                    subject_id=str(artifact_id),
                    payload_json=canonical_json_dumps({"commit_intent_id": str(commit_intent_id)}),
                    now_utc_ms=now,
                )
        self._wait(self._db_actor.submit(op))
        marker = final_path.with_name(final_path.name + f".{commit_intent_id}.commit.json")
        return CommitGrant(
            commit_intent_id=commit_intent_id,
            artifact_id=artifact_id,
            path_claim_id=path_claim_id,
            strategy=strategy,
            staging_path=staging,
            final_path=final_path,
            expected_size=expected_size,
            expected_sha256=expected_hash,
            marker_path=marker,
        )

    def finalize_commit(self, result: CommitResult) -> FinalizeResult:
        now = self._clock.utc_ms()
        row = self._wait(self._db_actor.submit(lambda c: get_commit_row(c, result.commit_intent_id)))
        if row is None:
            raise KeyError("commit intent not found")
        root = Path(str(row["normalized_root"]))
        final_path = resolve_contained(root, str(row["final_relative_path"]))
        reject_symlink(final_path, allow_missing=False)
        if not final_path.is_file():
            raise FileNotFoundError(final_path)
        size = final_path.stat().st_size
        digest = sha256_file(final_path)
        if size != int(row["expected_size"]) or digest != bytes(row["expected_sha256"]):
            raise ValueError("Core final verification failed")
        if size != result.size_bytes or digest != result.sha256:
            raise ValueError("Worker commit result disagrees with Core verification")
        artifact_id = ArtifactId.parse(str(row["artifact_id"]))
        if str(row["state"]) == "COMMITTED":
            existing = self._wait(self._db_actor.submit(lambda c: c.execute(
                "SELECT file_record_id,size_bytes,sha256 FROM file_records WHERE artifact_id=?",
                (str(artifact_id),),
            ).fetchone()))
            if existing is None or int(existing["size_bytes"]) != size or bytes(existing["sha256"]) != digest:
                raise RuntimeError("committed intent is missing its matching FileRecord")
            revision_row = self._wait(self._db_actor.submit(lambda c: c.execute(
                "SELECT state_revision FROM domain_events WHERE event_type='FILE_COMMITTED' AND subject_id=? ORDER BY event_id LIMIT 1",
                (str(artifact_id),),
            ).fetchone()))
            if revision_row is None:
                raise RuntimeError("committed artifact is missing FILE_COMMITTED event")
            return FinalizeResult(
                file_record_id=FileRecordId.parse(str(existing["file_record_id"])),
                committed_state_revision=int(revision_row["state_revision"]),
            )
        file_record_id = FileRecordId.new()
        path_claim_id = PathClaimId.parse(str(row["path_claim_id"]))
        storage_target_id = StorageTargetId.parse(str(row["storage_target_id"]))

        def op(connection):
            with write_transaction(connection):
                finalize_commit(
                    connection,
                    file_record_id=file_record_id,
                    commit_intent_id=result.commit_intent_id,
                    artifact_id=artifact_id,
                    path_claim_id=path_claim_id,
                    storage_target_id=storage_target_id,
                    storage_generation=int(row["storage_generation"]),
                    normalized_relative_path=str(row["final_relative_path"]),
                    size_bytes=size,
                    sha256=digest,
                    now_utc_ms=now,
                )
                # A committed final file no longer needs an active ResumeRecord.
                connection.execute("DELETE FROM resume_records WHERE artifact_id=?", (str(artifact_id),))
                revision = bump_state_revision(connection, now_utc_ms=now)
                append_domain_event(
                    connection,
                    state_revision=revision,
                    event_type="FILE_COMMITTED",
                    subject_kind="ARTIFACT",
                    subject_id=str(artifact_id),
                    payload_json=canonical_json_dumps({"file_record_id": str(file_record_id)}),
                    now_utc_ms=now,
                )
                return revision
        revision = self._wait(self._db_actor.submit(op))
        return FinalizeResult(file_record_id=file_record_id, committed_state_revision=revision)

    def register_resume_sidecar(self, sidecar_path: Path) -> ResumeState:
        # Core independently reads and validates the actual on-disk sidecar.
        state = read_resume_sidecar(sidecar_path)
        now = self._clock.utc_ms()
        self._wait(
            self._db_actor.submit(
                lambda connection: self._store_resume(connection, state, now)
            )
        )
        return state

    @staticmethod
    def _store_resume(connection, state: ResumeState, now: int) -> None:
        with write_transaction(connection):
            upsert_resume_record(connection, state, now_utc_ms=now)

    def recover_open_commits(self) -> list[RecoveryResult]:
        rows = self._wait(self._db_actor.submit(get_open_commit_rows))
        return [self._recover_row(row) for row in rows]

    def _recover_row(self, row) -> RecoveryResult:
        intent_id = CommitIntentId.parse(str(row["commit_intent_id"]))
        artifact_id = ArtifactId.parse(str(row["artifact_id"]))
        path_claim_id = PathClaimId.parse(str(row["path_claim_id"]))
        root = Path(str(row["normalized_root"]))
        staging = Path(str(row["staging_path"]))
        final_path = resolve_contained(root, str(row["final_relative_path"]))
        marker = final_path.with_name(final_path.name + f".{intent_id}.commit.json")
        now = self._clock.utc_ms()
        try:
            reject_symlink(staging)
            reject_symlink(final_path)
            reject_symlink(marker)
        except ValueError:
            self._mark_uncertain(intent_id, path_claim_id, now)
            return RecoveryResult(intent_id, RecoveryDisposition.REVIEW_REQUIRED, "symlink/reparse-like path")

        expected_size = int(row["expected_size"])
        expected_hash = bytes(row["expected_sha256"])
        strategy = FileCommitStrategy(str(row["strategy"]))
        if final_path.exists():
            if not final_path.is_file():
                self._mark_uncertain(intent_id, path_claim_id, now)
                return RecoveryResult(intent_id, RecoveryDisposition.REVIEW_REQUIRED, "final path is not regular file")
            valid = final_path.stat().st_size == expected_size and sha256_file(final_path) == expected_hash
            if not valid:
                self._mark_uncertain(intent_id, path_claim_id, now)
                return RecoveryResult(intent_id, RecoveryDisposition.REVIEW_REQUIRED, "final content mismatch")
            if strategy is FileCommitStrategy.COPY_VERIFY_COMMIT and not marker.is_file():
                self._mark_uncertain(intent_id, path_claim_id, now)
                return RecoveryResult(intent_id, RecoveryDisposition.REVIEW_REQUIRED, "copy marker missing")
            result = CommitResult(intent_id, expected_size, expected_hash, marker.is_file())
            self.finalize_commit(result)
            return RecoveryResult(intent_id, RecoveryDisposition.FINALIZED, "verified final adopted")
        if staging.exists() and staging.is_file():
            if staging.stat().st_size == expected_size and sha256_file(staging) == expected_hash:
                return RecoveryResult(intent_id, RecoveryDisposition.RETRY_COMMIT, "verified staging retained")
            self._mark_uncertain(intent_id, path_claim_id, now)
            return RecoveryResult(intent_id, RecoveryDisposition.REVIEW_REQUIRED, "staging content mismatch")
        self._mark_failed(intent_id, artifact_id, path_claim_id, now)
        return RecoveryResult(intent_id, RecoveryDisposition.FAILED, "staging and final both absent")

    def _mark_uncertain(self, intent_id: CommitIntentId, path_claim_id: PathClaimId, now: int) -> None:
        def op(connection):
            with write_transaction(connection):
                mark_commit_uncertain(
                    connection, commit_intent_id=intent_id, path_claim_id=path_claim_id, now_utc_ms=now
                )
        self._wait(self._db_actor.submit(op))

    def _mark_failed(
        self, intent_id: CommitIntentId, artifact_id: ArtifactId, path_claim_id: PathClaimId, now: int
    ) -> None:
        def op(connection):
            with write_transaction(connection):
                mark_commit_failed(
                    connection,
                    commit_intent_id=intent_id,
                    artifact_id=artifact_id,
                    path_claim_id=path_claim_id,
                    now_utc_ms=now,
                )
        self._wait(self._db_actor.submit(op))
