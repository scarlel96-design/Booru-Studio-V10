from __future__ import annotations

import sqlite3
from pathlib import Path

from booru_studio.common.ids import (
    ArtifactId,
    CommitIntentId,
    FileRecordId,
    JobId,
    ItemId,
    PathClaimId,
    StorageTargetId,
)
from booru_studio.domain.enums import ArtifactLifecycle, FileCommitState, FileSystemState, PathClaimState
from booru_studio.domain.file_commit import FileCommitStrategy


def insert_storage_target(
    connection: sqlite3.Connection,
    *,
    storage_target_id: StorageTargetId,
    generation: int,
    kind: str,
    normalized_root: str,
    identity_json: str,
    capability_json: str,
    now_utc_ms: int,
) -> None:
    connection.execute(
        """
        INSERT INTO storage_targets(
            storage_target_id,generation,kind,normalized_root,identity_json,capability_json,
            last_verified_at_utc_ms,created_at_utc_ms
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            str(storage_target_id), generation, kind, normalized_root, identity_json,
            capability_json, now_utc_ms, now_utc_ms,
        ),
    )


def insert_artifact_and_claim(
    connection: sqlite3.Connection,
    *,
    artifact_id: ArtifactId,
    path_claim_id: PathClaimId,
    job_id: JobId,
    item_id: ItemId | None,
    role: str,
    storage_target_id: StorageTargetId,
    storage_generation: int,
    normalized_relative_path: str,
    expected_size: int | None,
    expected_sha256: bytes | None,
    now_utc_ms: int,
) -> None:
    connection.execute(
        """
        INSERT INTO artifacts(
            artifact_id,job_id,item_id,role,lifecycle,filesystem_state,commit_owned,
            expected_size,sha256,created_at_utc_ms,updated_at_utc_ms
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            str(artifact_id), str(job_id), (None if item_id is None else str(item_id)), role, ArtifactLifecycle.PLANNED.value,
            FileSystemState.UNKNOWN.value, 0, expected_size, expected_sha256,
            now_utc_ms, now_utc_ms,
        ),
    )
    connection.execute(
        """
        INSERT INTO path_claims(
            path_claim_id,artifact_id,storage_target_id,storage_generation,
            normalized_relative_path,state,created_at_utc_ms,updated_at_utc_ms
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            str(path_claim_id), str(artifact_id), str(storage_target_id), storage_generation,
            normalized_relative_path, PathClaimState.CLAIMED.value, now_utc_ms, now_utc_ms,
        ),
    )


def prepare_commit_intent(
    connection: sqlite3.Connection,
    *,
    commit_intent_id: CommitIntentId,
    artifact_id: ArtifactId,
    path_claim_id: PathClaimId,
    strategy: FileCommitStrategy,
    staging_path: Path,
    final_relative_path: str,
    expected_size: int,
    expected_sha256: bytes,
    now_utc_ms: int,
) -> None:
    connection.execute(
        """
        INSERT INTO file_commit_intents(
            commit_intent_id,artifact_id,path_claim_id,strategy,state,staging_path,
            final_relative_path,expected_size,expected_sha256,prepared_at_utc_ms,terminal_at_utc_ms
        ) VALUES(?,?,?,?,?,?,?,?,?,?,NULL)
        """,
        (
            str(commit_intent_id), str(artifact_id), str(path_claim_id), strategy.value,
            FileCommitState.PREPARED.value, str(staging_path), final_relative_path,
            expected_size, expected_sha256, now_utc_ms,
        ),
    )
    cursor = connection.execute(
        """
        UPDATE artifacts
        SET lifecycle=?, commit_owned=1, updated_at_utc_ms=?
        WHERE artifact_id=? AND commit_owned=0
        """,
        (ArtifactLifecycle.VERIFIED.value, now_utc_ms, str(artifact_id)),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("artifact is not eligible for commit ownership")


def get_open_commit_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            """
            SELECT i.*, p.storage_target_id, p.storage_generation, s.normalized_root
            FROM file_commit_intents i
            JOIN path_claims p ON p.path_claim_id=i.path_claim_id
            JOIN storage_targets s
              ON s.storage_target_id=p.storage_target_id AND s.generation=p.storage_generation
            WHERE i.state IN ('PREPARED','UNCERTAIN')
            ORDER BY i.prepared_at_utc_ms, i.commit_intent_id
            """
        ).fetchall()
    )


def get_commit_row(connection: sqlite3.Connection, commit_intent_id: CommitIntentId) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT i.*, p.storage_target_id, p.storage_generation, s.normalized_root
        FROM file_commit_intents i
        JOIN path_claims p ON p.path_claim_id=i.path_claim_id
        JOIN storage_targets s
          ON s.storage_target_id=p.storage_target_id AND s.generation=p.storage_generation
        WHERE i.commit_intent_id=?
        """,
        (str(commit_intent_id),),
    ).fetchone()


def mark_commit_uncertain(
    connection: sqlite3.Connection,
    *,
    commit_intent_id: CommitIntentId,
    path_claim_id: PathClaimId,
    now_utc_ms: int,
) -> None:
    connection.execute(
        "UPDATE file_commit_intents SET state='UNCERTAIN' WHERE commit_intent_id=?",
        (str(commit_intent_id),),
    )
    connection.execute(
        "UPDATE path_claims SET state='RECOVERY_REQUIRED',updated_at_utc_ms=? WHERE path_claim_id=?",
        (now_utc_ms, str(path_claim_id)),
    )


def mark_commit_failed(
    connection: sqlite3.Connection,
    *,
    commit_intent_id: CommitIntentId,
    artifact_id: ArtifactId,
    path_claim_id: PathClaimId,
    now_utc_ms: int,
) -> None:
    connection.execute(
        "UPDATE file_commit_intents SET state='FAILED',terminal_at_utc_ms=? WHERE commit_intent_id=?",
        (now_utc_ms, str(commit_intent_id)),
    )
    connection.execute(
        "UPDATE artifacts SET lifecycle='FAILED',updated_at_utc_ms=? WHERE artifact_id=?",
        (now_utc_ms, str(artifact_id)),
    )
    connection.execute(
        "UPDATE path_claims SET state='RECOVERY_REQUIRED',updated_at_utc_ms=? WHERE path_claim_id=?",
        (now_utc_ms, str(path_claim_id)),
    )


def finalize_commit(
    connection: sqlite3.Connection,
    *,
    file_record_id: FileRecordId,
    commit_intent_id: CommitIntentId,
    artifact_id: ArtifactId,
    path_claim_id: PathClaimId,
    storage_target_id: StorageTargetId,
    storage_generation: int,
    normalized_relative_path: str,
    size_bytes: int,
    sha256: bytes,
    now_utc_ms: int,
) -> None:
    existing = connection.execute(
        "SELECT file_record_id,size_bytes,sha256 FROM file_records WHERE artifact_id=?",
        (str(artifact_id),),
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            INSERT INTO file_records(
                file_record_id,artifact_id,storage_target_id,storage_generation,
                normalized_relative_path,size_bytes,sha256,filesystem_state,
                committed_at_utc_ms,last_verified_at_utc_ms
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(file_record_id), str(artifact_id), str(storage_target_id), storage_generation,
                normalized_relative_path, size_bytes, sha256, FileSystemState.PRESENT.value,
                now_utc_ms, now_utc_ms,
            ),
        )
    else:
        if int(existing["size_bytes"]) != size_bytes or bytes(existing["sha256"]) != sha256:
            raise RuntimeError("existing file record conflicts with verified final file")
    connection.execute(
        """
        UPDATE artifacts
        SET lifecycle='COMMITTED',filesystem_state='PRESENT',commit_owned=1,
            expected_size=?,sha256=?,updated_at_utc_ms=?
        WHERE artifact_id=?
        """,
        (size_bytes, sha256, now_utc_ms, str(artifact_id)),
    )
    connection.execute(
        "UPDATE path_claims SET state='COMMITTED',updated_at_utc_ms=? WHERE path_claim_id=?",
        (now_utc_ms, str(path_claim_id)),
    )
    connection.execute(
        "UPDATE file_commit_intents SET state='COMMITTED',terminal_at_utc_ms=? WHERE commit_intent_id=?",
        (now_utc_ms, str(commit_intent_id)),
    )
