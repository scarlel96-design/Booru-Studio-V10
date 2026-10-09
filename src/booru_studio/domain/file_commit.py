from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from booru_studio.common.ids import (
    ArtifactId,
    CommitIntentId,
    FileRecordId,
    PathClaimId,
    StorageTargetId,
)


class FileCommitStrategy(StrEnum):
    ATOMIC_RENAME = "ATOMIC_RENAME"
    VERIFIED_RENAME = "VERIFIED_RENAME"
    COPY_VERIFY_COMMIT = "COPY_VERIFY_COMMIT"


class RecoveryDisposition(StrEnum):
    RETRY_COMMIT = "RETRY_COMMIT"
    FINALIZED = "FINALIZED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class StorageTarget:
    storage_target_id: StorageTargetId
    generation: int
    kind: str
    root: Path
    identity_json: str = "{}"
    capability_json: str = "{}"


@dataclass(frozen=True, slots=True)
class ArtifactPlan:
    artifact_id: ArtifactId
    path_claim_id: PathClaimId
    staging_path: Path
    final_path: Path
    normalized_relative_path: str


@dataclass(frozen=True, slots=True)
class CommitGrant:
    commit_intent_id: CommitIntentId
    artifact_id: ArtifactId
    path_claim_id: PathClaimId
    strategy: FileCommitStrategy
    staging_path: Path
    final_path: Path
    expected_size: int
    expected_sha256: bytes
    marker_path: Path


@dataclass(frozen=True, slots=True)
class CommitResult:
    commit_intent_id: CommitIntentId
    size_bytes: int
    sha256: bytes
    marker_written: bool


@dataclass(frozen=True, slots=True)
class FinalizeResult:
    file_record_id: FileRecordId
    committed_state_revision: int


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    commit_intent_id: CommitIntentId
    disposition: RecoveryDisposition
    detail: str
