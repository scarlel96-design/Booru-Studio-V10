from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from booru_studio.common.ids import ArtifactId


@dataclass(frozen=True, slots=True)
class ResumeState:
    artifact_id: ArtifactId
    generation: int
    part_path: Path
    sidecar_path: Path
    part_size: int
    source_fingerprint: str
    validator: dict[str, object]
    payload_checksum: bytes
