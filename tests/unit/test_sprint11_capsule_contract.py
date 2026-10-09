from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from booru_studio.packaging.install_state import InstallState, InstallStateStore
from booru_studio.packaging.manifest import AppManifest, ManifestValidationError
from booru_studio.runtime.launcher import prepare_capsule_launch


def _manifest(root: Path, *, path: str = "bin/core.exe") -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"core")
    supervisor = root / "bin/supervisor.exe"; supervisor.write_bytes(b"supervisor")
    ui = root / "bin/ui.exe"; ui.write_bytes(b"ui")
    worker = root / "bin/worker.exe"; worker.write_bytes(b"worker")
    entries = [target, supervisor, ui, worker]
    files = [
        {"path": item.relative_to(root).as_posix(), "size": item.stat().st_size,
         "sha256": hashlib.sha256(item.read_bytes()).hexdigest(), "role": "runtime"}
        for item in entries
    ]
    data = {"product": "Booru Studio", "version": "10", "build": "b1", "capsule_id": "c1",
            "protocol": {"ui_core": 1}, "db_schema": {"minimum": 1, "maximum": 1},
            "release_sequence": 1,
            "entrypoints": {"ui": "bin/ui.exe", "core": path, "worker": "bin/worker.exe", "supervisor": "bin/supervisor.exe"},
            "files": files}
    file = root / "app-manifest.json"; file.write_text(json.dumps(data), encoding="utf-8")
    return file


def test_capsule_inventory_rejects_extra_and_case_collision(tmp_path: Path) -> None:
    manifest = AppManifest.load(_manifest(tmp_path))
    manifest.verify_capsule(tmp_path)
    (tmp_path / "extra.dll").write_bytes(b"x")
    with pytest.raises(ManifestValidationError, match="extra"):
        manifest.verify_capsule(tmp_path)
    payload = json.loads((tmp_path / "app-manifest.json").read_text(encoding="utf-8"))
    payload["files"].append({**payload["files"][0], "path": "BIN/CORE.EXE"})
    (tmp_path / "app-manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ManifestValidationError, match="case-colliding"):
        AppManifest.load(tmp_path / "app-manifest.json")


def test_install_state_replaces_atomically_and_launcher_uses_supplied_endpoint(tmp_path: Path) -> None:
    store = InstallStateStore(tmp_path / "state" / "install-state.json")
    store.save(InstallState(1, "c2", "c1"))
    assert store.load().active_capsule_id == "c2"
    capsule = tmp_path / "capsule"; capsule.mkdir(); _manifest(capsule)
    launch = prepare_capsule_launch(capsule_root=capsule, state_db=tmp_path / "state.db", endpoint="booru-v10-core-test")
    assert launch.command()[2:4] == ["--endpoint", "booru-v10-core-test"]
