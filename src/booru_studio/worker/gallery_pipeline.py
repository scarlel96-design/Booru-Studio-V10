from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from booru_studio.engine.adapters.gallery_dl import GalleryDlAdapter, GalleryDirectHandoffPlanner
from booru_studio.engine.contracts import CandidateArtifact, NormalizedItemDescriptor, ProbeResult


@dataclass(frozen=True, slots=True)
class GalleryDiscoveryBatch:
    sequence: int
    items: tuple[NormalizedItemDescriptor, ...]

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("gallery discovery batch sequence cannot be negative")
        if not self.items:
            raise ValueError("gallery discovery batch cannot be empty")


@dataclass(frozen=True, slots=True)
class GalleryWorkerDiscovery:
    source_kind: str
    batches: tuple[GalleryDiscoveryBatch, ...]
    queued_inputs: tuple[str, ...]
    completeness: str

    @property
    def item_count(self) -> int:
        return sum(len(batch.items) for batch in self.batches)


class GalleryWorkerPipeline:
    """Worker-owned façade for the concrete gallery-dl adapter.

    Core only deals in normalized discovery state and ephemeral execution contracts.  Keeping this
    façade in ``booru_studio.worker`` makes the ownership rule executable: importing Core never loads
    gallery-dl, while a Job Worker can probe/discover and create a DirectHTTP handoff plan.

    Sprint 6 intentionally bounds the Worker→Core crossing to small batches.  gallery-dl's current
    high-level DataJob API still materializes the extraction result inside the Worker; that is bounded
    by the adapter's hard item ceiling and does not become an unbounded DB/UI materialization.
    """

    _MAX_BATCH = 500

    def __init__(self, adapter: GalleryDlAdapter | None = None) -> None:
        self._adapter = adapter or GalleryDlAdapter()

    def probe(self, raw_input: str) -> ProbeResult:
        return self._adapter.probe(raw_input)

    def discover(self, raw_input: str, *, batch_size: int = 250) -> GalleryWorkerDiscovery:
        if not 1 <= batch_size <= self._MAX_BATCH:
            raise ValueError(f"gallery batch_size must be between 1 and {self._MAX_BATCH}")
        result = self._adapter.discover(raw_input)
        batches = tuple(
            GalleryDiscoveryBatch(
                sequence=sequence,
                items=tuple(result.items[start:start + batch_size]),
            )
            for sequence, start in enumerate(range(0, len(result.items), batch_size))
        )
        return GalleryWorkerDiscovery(
            source_kind=result.source_kind,
            batches=batches,
            queued_inputs=tuple(result.queued_inputs),
            completeness=result.completeness,
        )

    @staticmethod
    def build_direct_handoff(
        candidate: CandidateArtifact,
        *,
        artifact_id: str,
        generation: int,
        staging_path: Path,
    ) -> dict[str, object]:
        return GalleryDirectHandoffPlanner.build(
            candidate,
            artifact_id=artifact_id,
            generation=generation,
            staging_path=staging_path,
        )
