from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from booru_studio.packaging.manifest import AppManifest


def create_endpoint() -> str:
    """Create one opaque endpoint for the Launcher, Supervisor and Core.

    The supervisor must receive this value rather than independently deriving one; otherwise the
    UI and Core can be pointed at different local servers during startup.
    """
    return f"booru-v10-core-{os.getpid()}-{secrets.token_hex(16)}"


@dataclass(frozen=True, slots=True)
class CapsuleLaunch:
    supervisor: Path
    core: Path
    state_db: Path
    endpoint: str

    def command(self) -> list[str]:
        return [
            str(self.supervisor), str(self.core), "--endpoint", self.endpoint,
            "--state-db", str(self.state_db),
        ]


def prepare_capsule_launch(*, capsule_root: Path, state_db: Path, endpoint: str | None = None) -> CapsuleLaunch:
    manifest = AppManifest.load(capsule_root / "app-manifest.json")
    manifest.verify_capsule(capsule_root)
    selected_endpoint = endpoint or create_endpoint()
    if not selected_endpoint.startswith("booru-v10-core-") or len(selected_endpoint) > 240:
        raise ValueError("invalid local endpoint name")
    return CapsuleLaunch(
        supervisor=capsule_root / manifest.entrypoints["supervisor"],
        core=capsule_root / manifest.entrypoints["core"],
        state_db=state_db,
        endpoint=selected_endpoint,
    )
