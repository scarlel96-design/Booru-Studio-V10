from __future__ import annotations

from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import TypeVar

from booru_studio.common.clock import Clock
from booru_studio.common.ids import DiscoveryCycleId, ItemId, JobId
from booru_studio.common.serialization import canonical_json_dumps
from booru_studio.domain.enums import DiscoveryCompleteness
from booru_studio.engine.contracts import NormalizedItemDescriptor
from booru_studio.persistence.db_actor import DbActor
from booru_studio.persistence.repositories.discovery_repository import (
    insert_cycle, insert_item_batch, list_items, next_cycle_sequence, seal_cycle,
)
from booru_studio.persistence.repositories.state_repository import append_domain_event, bump_state_revision
from booru_studio.persistence.transactions.base import write_transaction

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PersistedDiscoveryItem:
    item_id: ItemId
    descriptor: NormalizedItemDescriptor


class DiscoveryService:
    """Durable half of streaming discovery.

    Only normalized/redacted fields are stored. Candidate TransferDescriptors remain in Worker/Core
    runtime memory and are never accepted by this service.
    """

    def __init__(self, db_actor: DbActor, clock: Clock, *, db_timeout_s: float = 5.0) -> None:
        self._db = db_actor
        self._clock = clock
        self._timeout = db_timeout_s

    def _wait(self, future: Future[T]) -> T:
        try:
            return future.result(timeout=self._timeout)
        except FutureTimeoutError as exc:
            raise TimeoutError("database operation timed out") from exc

    def begin(self, job_id: JobId) -> DiscoveryCycleId:
        cycle_id = DiscoveryCycleId.new()
        now = self._clock.utc_ms()
        def op(connection):
            with write_transaction(connection):
                if connection.execute("SELECT 1 FROM jobs WHERE job_id=?", (str(job_id),)).fetchone() is None:
                    raise KeyError("Job not found")
                sequence = next_cycle_sequence(connection, job_id)
                insert_cycle(connection, cycle_id=cycle_id, job_id=job_id, sequence=sequence, now_utc_ms=now)
                revision = bump_state_revision(connection, now_utc_ms=now)
                append_domain_event(
                    connection, state_revision=revision, event_type="DISCOVERY_OPENED",
                    subject_kind="JOB", subject_id=str(job_id),
                    payload_json=canonical_json_dumps({"cycle_id": str(cycle_id), "sequence": sequence}),
                    now_utc_ms=now,
                )
        self._wait(self._db.submit(op))
        return cycle_id

    def ingest_batch(
        self, *, job_id: JobId, cycle_id: DiscoveryCycleId, batch_sequence: int,
        descriptors: list[NormalizedItemDescriptor],
    ) -> list[PersistedDiscoveryItem]:
        if batch_sequence < 0:
            raise ValueError("batch_sequence cannot be negative")
        if len(descriptors) > 500:
            raise ValueError("discovery batch exceeds 500 items")
        now = self._clock.utc_ms()
        pairs = [PersistedDiscoveryItem(ItemId.new(), descriptor) for descriptor in descriptors]
        rows = [
            {
                "item_id": pair.item_id,
                "source_key": pair.descriptor.source_identity,
                "display_title": pair.descriptor.display_title,
                "source_index": pair.descriptor.source_index,
            }
            for pair in pairs
        ]
        def op(connection):
            with write_transaction(connection):
                insert_item_batch(
                    connection, cycle_id=cycle_id, job_id=job_id, batch_sequence=batch_sequence,
                    items=rows, now_utc_ms=now,
                )
                revision = bump_state_revision(connection, now_utc_ms=now)
                append_domain_event(
                    connection, state_revision=revision, event_type="DISCOVERY_BATCH_COMMITTED",
                    subject_kind="JOB", subject_id=str(job_id),
                    payload_json=canonical_json_dumps({
                        "cycle_id": str(cycle_id), "batch_sequence": batch_sequence,
                        "offered_count": len(rows),
                    }), now_utc_ms=now,
                )
        self._wait(self._db.submit(op))
        # Duplicates may have been ignored by the DB unique source key. Return only rows that exist
        # under the IDs allocated for this batch; callers can re-resolve duplicates on a later cycle.
        present = set(self._wait(self._db.submit(lambda c: {
            str(row[0]) for row in c.execute(
                f"SELECT item_id FROM items WHERE item_id IN ({','.join('?' for _ in pairs)})",
                tuple(str(pair.item_id) for pair in pairs),
            ).fetchall()
        }))) if pairs else set()
        return [pair for pair in pairs if str(pair.item_id) in present]

    def seal(self, cycle_id: DiscoveryCycleId, *, completeness: DiscoveryCompleteness = DiscoveryCompleteness.COMPLETE) -> None:
        now = self._clock.utc_ms()
        def op(connection):
            with write_transaction(connection):
                row = connection.execute("SELECT job_id FROM discovery_cycles WHERE cycle_id=?", (str(cycle_id),)).fetchone()
                if row is None:
                    raise KeyError("discovery cycle not found")
                seal_cycle(connection, cycle_id=cycle_id, completeness=completeness, now_utc_ms=now)
                revision = bump_state_revision(connection, now_utc_ms=now)
                append_domain_event(
                    connection, state_revision=revision, event_type="DISCOVERY_SEALED",
                    subject_kind="JOB", subject_id=str(row["job_id"]),
                    payload_json=canonical_json_dumps({"cycle_id": str(cycle_id), "completeness": completeness.value}),
                    now_utc_ms=now,
                )
        self._wait(self._db.submit(op))

    def list_items(self, job_id: JobId):
        return self._wait(self._db.submit(lambda c: list_items(c, job_id)))
