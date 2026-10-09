from __future__ import annotations

from pathlib import Path

import pytest

from booru_studio.engine.adapters.gallery_dl import GalleryDlAdapter, GalleryDlRecord
from booru_studio.engine.contracts import HandoffSafety
from booru_studio.worker.gallery_pipeline import GalleryWorkerPipeline


class FakeBackend:
    def __init__(self, records):
        self.records = tuple(records)

    def collect(self, raw_input: str):
        return self.records


def _records(count: int):
    return tuple(
        GalleryDlRecord(3, f"https://cdn.test/{i}.jpg", {
            "category": "example", "id": i, "filename": f"image-{i}", "extension": "jpg",
        })
        for i in range(count)
    )


def test_worker_owns_gallery_adapter_and_bounds_crossing_batches() -> None:
    pipeline = GalleryWorkerPipeline(GalleryDlAdapter(FakeBackend(_records(1201))))
    result = pipeline.discover("https://example.test/gallery", batch_size=500)
    assert result.item_count == 1201
    assert [len(batch.items) for batch in result.batches] == [500, 500, 201]
    assert [batch.sequence for batch in result.batches] == [0, 1, 2]
    assert all(
        item.candidate_artifacts[0].descriptor.handoff_safety is HandoffSafety.SAFE
        for batch in result.batches for item in batch.items
    )


def test_worker_gallery_batch_limit_and_direct_handoff_boundary() -> None:
    pipeline = GalleryWorkerPipeline(GalleryDlAdapter(FakeBackend(_records(1))))
    with pytest.raises(ValueError, match="batch_size"):
        pipeline.discover("https://example.test/gallery", batch_size=501)

    item = pipeline.discover("https://example.test/gallery").batches[0].items[0]
    wire = pipeline.build_direct_handoff(
        item.candidate_artifacts[0],
        artifact_id="00000000-0000-0000-0000-000000000000",
        generation=1,
        staging_path=Path("staging/file.part"),
    )
    assert wire["url"] == "https://cdn.test/0.jpg"
    assert wire["generation"] == 1
