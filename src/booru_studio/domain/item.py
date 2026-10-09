from __future__ import annotations

from dataclasses import dataclass

from booru_studio.common.ids import DiscoveryCycleId, ItemId, JobId
from booru_studio.domain.enums import ItemDisposition, ItemLifecycle, ItemOutcome


@dataclass(slots=True)
class Item:
    item_id: ItemId
    job_id: JobId
    discovery_cycle_id: DiscoveryCycleId | None
    source_key: str | None
    display_title: str
    lifecycle: ItemLifecycle = ItemLifecycle.PENDING
    outcome: ItemOutcome | None = None
    disposition: ItemDisposition | None = None
    source_index: int | None = None
    created_at_utc_ms: int = 0
    updated_at_utc_ms: int = 0
