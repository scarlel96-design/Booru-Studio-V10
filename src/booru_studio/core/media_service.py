from __future__ import annotations

from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Sequence, TypeVar

from booru_studio.common.clock import Clock
from booru_studio.common.ids import CollectionId, JobId
from booru_studio.common.serialization import canonical_json_dumps
from booru_studio.core.discovery_service import DiscoveryService, PersistedDiscoveryItem
from booru_studio.core.job_service import JobService
from booru_studio.domain.enums import DiscoveryCompleteness, JobKind
from booru_studio.domain.presentation import CollectionSemantics, MediaPresentationContract, PresentationMode
from booru_studio.engine.contracts import NormalizedItemDescriptor
from booru_studio.persistence.db_actor import DbActor
from booru_studio.persistence.repositories.collection_repository import (
    add_collection_memberships,
    get_or_create_collection,
)
from booru_studio.persistence.repositories.state_repository import append_domain_event, bump_state_revision
from booru_studio.persistence.transactions.base import write_transaction

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class MediaDiscoveryCommit:
    job_id: JobId
    job_kind: JobKind
    presentation: MediaPresentationContract
    items: tuple[PersistedDiscoveryItem, ...]
    collection_id: CollectionId | None = None


class MediaService:
    """Core-side durable coordinator for normalized media discovery.

    The service accepts only normalized descriptors. Candidate transfer URLs, headers, cookies,
    format dictionaries and other engine runtime state are intentionally absent from its API.
    """

    _MAX_BATCH = 500
    _MAX_COLLECTION_KEY = 512
    _MAX_COLLECTION_TITLE = 1024

    def __init__(self, db_actor: DbActor, clock: Clock, *, db_timeout_s: float = 5.0) -> None:
        self._db = db_actor
        self._clock = clock
        self._timeout = db_timeout_s
        self._jobs = JobService(db_actor, clock, db_timeout_s=db_timeout_s)
        self._discovery = DiscoveryService(db_actor, clock, db_timeout_s=db_timeout_s)

    def _wait(self, future: Future[T]) -> T:
        try:
            return future.result(timeout=self._timeout)
        except FutureTimeoutError as exc:
            raise TimeoutError("database operation timed out") from exc

    @staticmethod
    def _validate_collection_identity(value: str) -> str:
        value = value.strip()
        if not value or len(value) > MediaService._MAX_COLLECTION_KEY:
            raise ValueError("collection identity is missing or too long")
        # Runtime URLs and signed locators do not belong in the durable collection source key.
        if "://" in value or "?" in value or "#" in value:
            raise ValueError("collection identity must be a normalized opaque source key")
        return value

    @staticmethod
    def _validate_collection_title(value: str) -> str:
        value = value.replace("\x00", " ").strip()
        if not value:
            return "Media collection"
        return value[: MediaService._MAX_COLLECTION_TITLE]

    def commit_discovery(
        self,
        *,
        job_id: JobId,
        presentation: MediaPresentationContract,
        batches: Sequence[Sequence[NormalizedItemDescriptor]],
        completeness: DiscoveryCompleteness,
        collection_identity: str | None = None,
        collection_title: str | None = None,
    ) -> MediaDiscoveryCommit:
        normalized_batches = tuple(tuple(batch) for batch in batches)
        if any(len(batch) > self._MAX_BATCH for batch in normalized_batches):
            raise ValueError("media discovery batch exceeds 500 items")
        total = sum(len(batch) for batch in normalized_batches)

        if presentation.mode is PresentationMode.INDIVIDUAL:
            if presentation.collection is not CollectionSemantics.NONE or total != 1:
                raise ValueError("individual media discovery must contain exactly one item")
            if collection_identity is not None:
                raise ValueError("individual media discovery cannot carry a collection identity")
            job_kind = JobKind.SINGLE_MEDIA
        else:
            if presentation.collection is CollectionSemantics.NONE:
                raise ValueError("batch media discovery requires collection semantics")
            if collection_identity is None:
                raise ValueError("batch media discovery requires a normalized collection identity")
            job_kind = JobKind.COLLECTION_MEDIA

        self._jobs.classify_job(job_id, job_kind)
        cycle_id = self._discovery.begin(job_id)
        persisted: list[PersistedDiscoveryItem] = []
        for sequence, batch in enumerate(normalized_batches):
            if not batch:
                continue
            persisted.extend(self._discovery.ingest_batch(
                job_id=job_id,
                cycle_id=cycle_id,
                batch_sequence=sequence,
                descriptors=list(batch),
            ))
        self._discovery.seal(cycle_id, completeness=completeness)

        collection_id: CollectionId | None = None
        if presentation.mode is PresentationMode.BATCH:
            assert collection_identity is not None
            source_key = self._validate_collection_identity(collection_identity)
            title = self._validate_collection_title(collection_title or "")
            proposed = CollectionId.new()
            now = self._clock.utc_ms()

            def op(connection):
                with write_transaction(connection):
                    actual = get_or_create_collection(
                        connection,
                        collection_id=proposed,
                        job_id=job_id,
                        kind=presentation.collection.value,
                        title=title,
                        source_key=source_key,
                        now_utc_ms=now,
                    )
                    positions = [
                        (item.item_id, item.descriptor.discovery_sequence)
                        for item in persisted
                    ]
                    add_collection_memberships(connection, collection_id=actual, memberships=positions)
                    revision = bump_state_revision(connection, now_utc_ms=now)
                    append_domain_event(
                        connection,
                        state_revision=revision,
                        event_type="MEDIA_COLLECTION_LINKED",
                        subject_kind="JOB",
                        subject_id=str(job_id),
                        payload_json=canonical_json_dumps({
                            "collection_id": str(actual),
                            "collection_kind": presentation.collection.value,
                            "member_count": len(positions),
                        }),
                        now_utc_ms=now,
                    )
                    return actual

            collection_id = self._wait(self._db.submit(op))

        return MediaDiscoveryCommit(
            job_id=job_id,
            job_kind=job_kind,
            presentation=presentation,
            items=tuple(persisted),
            collection_id=collection_id,
        )
