from __future__ import annotations

from dataclasses import dataclass

from booru_studio.common.ids import ArtifactId, ItemId, JobId, PathClaimId
from booru_studio.domain.enums import ArtifactLifecycle, CommitOwnership, FileSystemState


@dataclass(slots=True)
class Artifact:
    artifact_id: ArtifactId
    job_id: JobId
    item_id: ItemId | None
    role: str
    lifecycle: ArtifactLifecycle = ArtifactLifecycle.PLANNED
    filesystem_state: FileSystemState = FileSystemState.UNKNOWN
    commit_ownership: CommitOwnership = CommitOwnership.PRE_COMMIT
    path_claim_id: PathClaimId | None = None
    expected_size: int | None = None
    sha256_hex: str | None = None
    created_at_utc_ms: int = 0
    updated_at_utc_ms: int = 0
