from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from booru_studio.common.ids import ArtifactId
from booru_studio.common.paths import reject_symlink
from booru_studio.common.serialization import canonical_json_dumps, json_loads_object
from booru_studio.domain.resume import ResumeState

_MAX_SIDECAR_BYTES = 64 * 1024


def _body(
    *, artifact_id: ArtifactId, generation: int, part_path: Path, part_size: int,
    source_fingerprint: str, validator: dict[str, object]
) -> dict[str, object]:
    return {
        "schema": 1,
        "artifact_id": str(artifact_id),
        "generation": generation,
        "part_path": str(part_path),
        "part_size": part_size,
        "source_fingerprint": source_fingerprint,
        "validator": validator,
    }


def write_resume_sidecar(
    *, artifact_id: ArtifactId, generation: int, part_path: Path, sidecar_path: Path,
    source_fingerprint: str, validator: dict[str, object]
) -> ResumeState:
    reject_symlink(part_path, allow_missing=False)
    reject_symlink(sidecar_path)
    part_size = part_path.stat().st_size
    body = _body(
        artifact_id=artifact_id, generation=generation, part_path=part_path,
        part_size=part_size, source_fingerprint=source_fingerprint, validator=validator,
    )
    checksum = hashlib.sha256(canonical_json_dumps(body).encode("utf-8")).hexdigest()
    envelope = {"payload": body, "checksum": checksum}
    encoded = canonical_json_dumps(envelope).encode("utf-8")
    if len(encoded) > _MAX_SIDECAR_BYTES:
        raise ValueError("resume sidecar is too large")
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = sidecar_path.with_name(sidecar_path.name + ".tmp")
    reject_symlink(tmp)
    if tmp.exists():
        if not tmp.is_file():
            raise ValueError("resume sidecar temporary path is not a regular file")
        tmp.unlink()
    with tmp.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, sidecar_path)
    return read_resume_sidecar(sidecar_path)


def read_resume_sidecar(sidecar_path: Path) -> ResumeState:
    reject_symlink(sidecar_path, allow_missing=False)
    raw = sidecar_path.read_bytes()
    if len(raw) > _MAX_SIDECAR_BYTES:
        raise ValueError("resume sidecar is too large")
    obj = json_loads_object(raw.decode("utf-8"))
    payload = obj.get("payload")
    if not isinstance(payload, dict) or not isinstance(obj.get("checksum"), str):
        raise ValueError("invalid resume sidecar envelope")
    expected = hashlib.sha256(canonical_json_dumps(payload).encode("utf-8")).hexdigest()
    if not __import__('hmac').compare_digest(expected, str(obj["checksum"])):
        raise ValueError("resume sidecar checksum mismatch")
    if payload.get("schema") != 1:
        raise ValueError("unsupported resume sidecar schema")
    part_path = Path(str(payload["part_path"]))
    reject_symlink(part_path, allow_missing=False)
    actual_size = part_path.stat().st_size
    if actual_size != int(payload["part_size"]):
        raise ValueError("resume sidecar part-size mismatch")
    checksum_bytes = hashlib.sha256(canonical_json_dumps(payload).encode("utf-8")).digest()
    validator = payload.get("validator")
    if not isinstance(validator, dict):
        raise ValueError("validator must be an object")
    return ResumeState(
        artifact_id=ArtifactId.parse(str(payload["artifact_id"])),
        generation=int(payload["generation"]),
        part_path=part_path,
        sidecar_path=sidecar_path,
        part_size=actual_size,
        source_fingerprint=str(payload["source_fingerprint"]),
        validator=dict(validator),
        payload_checksum=checksum_bytes,
    )


def recover_resume_checkpoint(sidecar_path: Path) -> ResumeState:
    """Recover to the last durable sidecar checkpoint.

    A crash can leave the .part file ahead of the atomically replaced sidecar. Bytes
    beyond the sidecar's recorded size were never checkpoint-authoritative, so they
    are truncated before returning the normal strict ResumeState. A shorter part is
    rejected because data promised by the sidecar is missing.
    """
    reject_symlink(sidecar_path, allow_missing=False)
    raw = sidecar_path.read_bytes()
    if len(raw) > _MAX_SIDECAR_BYTES:
        raise ValueError("resume sidecar is too large")
    obj = json_loads_object(raw.decode("utf-8"))
    payload = obj.get("payload")
    if not isinstance(payload, dict) or not isinstance(obj.get("checksum"), str):
        raise ValueError("invalid resume sidecar envelope")
    expected = hashlib.sha256(canonical_json_dumps(payload).encode("utf-8")).hexdigest()
    if not __import__("hmac").compare_digest(expected, str(obj["checksum"])):
        raise ValueError("resume sidecar checksum mismatch")
    if payload.get("schema") != 1:
        raise ValueError("unsupported resume sidecar schema")
    part_path = Path(str(payload["part_path"]))
    reject_symlink(part_path, allow_missing=False)
    recorded_size = int(payload["part_size"])
    if recorded_size < 0:
        raise ValueError("resume sidecar part-size is negative")
    actual_size = part_path.stat().st_size
    if actual_size < recorded_size:
        raise ValueError("partial file is shorter than its durable checkpoint")
    if actual_size > recorded_size:
        with part_path.open("r+b") as handle:
            handle.truncate(recorded_size)
            handle.flush()
            os.fsync(handle.fileno())
    return read_resume_sidecar(sidecar_path)
