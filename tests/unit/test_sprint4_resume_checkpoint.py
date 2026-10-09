from __future__ import annotations

from pathlib import Path

from booru_studio.common.ids import ArtifactId
from booru_studio.worker.resume import recover_resume_checkpoint, write_resume_sidecar


def test_recover_checkpoint_truncates_bytes_written_after_last_durable_sidecar(tmp_path: Path) -> None:
    artifact = ArtifactId.new()
    part = tmp_path / "x.part"; sidecar = tmp_path / "x.resume.json"
    part.write_bytes(b"a" * 100)
    write_resume_sidecar(
        artifact_id=artifact, generation=1, part_path=part, sidecar_path=sidecar,
        source_fingerprint="source", validator={"if_range": '"v1"', "total": 200},
    )
    with part.open("ab") as handle:
        handle.write(b"uncheckpointed")
    state = recover_resume_checkpoint(sidecar)
    assert state.part_size == 100
    assert part.read_bytes() == b"a" * 100


def test_atomic_sidecar_writer_recovers_stale_regular_tmp_file(tmp_path: Path) -> None:
    artifact = ArtifactId.new()
    part = tmp_path / "x.part"; sidecar = tmp_path / "x.resume.json"
    part.write_bytes(b"abc")
    tmp = sidecar.with_name(sidecar.name + ".tmp")
    tmp.write_text("stale", encoding="utf-8")
    state = write_resume_sidecar(
        artifact_id=artifact, generation=1, part_path=part, sidecar_path=sidecar,
        source_fingerprint="source", validator={"if_range": '"v1"'},
    )
    assert state.part_size == 3
    assert not tmp.exists()
