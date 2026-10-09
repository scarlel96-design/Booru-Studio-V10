from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class InstallState:
    schema_version: int
    active_capsule_id: str
    previous_capsule_id: str | None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported install-state schema")
        if not self.active_capsule_id:
            raise ValueError("active_capsule_id is required")


class InstallStateStore:
    """Atomically updates the tiny launcher-owned capsule pointer."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> InstallState:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if set(raw) != {"schema_version", "active_capsule_id", "previous_capsule_id"}:
            raise ValueError("invalid install-state fields")
        return InstallState(**raw)

    def save(self, state: InstallState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(asdict(state), handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
