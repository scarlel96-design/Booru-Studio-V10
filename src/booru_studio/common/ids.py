from __future__ import annotations

from dataclasses import dataclass
from typing import Self
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True, order=True)
class EntityId:
    """Opaque UUID-backed identifier.

    Concrete subclasses intentionally prevent accidental mixing of JobId, RunId,
    ItemId, etc. at both review time and under static type checking.
    """

    value: UUID

    @classmethod
    def new(cls) -> Self:
        return cls(uuid4())

    @classmethod
    def parse(cls, raw: str) -> Self:
        return cls(UUID(raw))

    def __str__(self) -> str:
        return str(self.value)


class SubmissionId(EntityId):
    pass


class JobId(EntityId):
    pass


class JobRunId(EntityId):
    pass


class DiscoveryCycleId(EntityId):
    pass


class ItemId(EntityId):
    pass


class ArtifactId(EntityId):
    pass


class FileRecordId(EntityId):
    pass


class CommandId(EntityId):
    pass


class ClientInstanceId(EntityId):
    pass


class AttemptId(EntityId):
    pass


class OperationId(EntityId):
    pass


class CollectionId(EntityId):
    pass


class RetryEpisodeId(EntityId):
    pass


class RecoveryEpisodeId(EntityId):
    pass


class StorageTargetId(EntityId):
    pass


class PathClaimId(EntityId):
    pass


class CommitIntentId(EntityId):
    pass


class CleanupObligationId(EntityId):
    pass


class EnginePackId(EntityId):
    pass


class CoreInstanceId(EntityId):
    pass


class WorkerSessionId(EntityId):
    pass
