from __future__ import annotations

from booru_studio.common.ids import ArtifactId, JobId


def test_entity_ids_round_trip() -> None:
    job_id = JobId.new()
    assert JobId.parse(str(job_id)) == job_id


def test_concrete_id_types_are_distinct() -> None:
    raw = JobId.new().value
    assert JobId(raw) != ArtifactId(raw)
