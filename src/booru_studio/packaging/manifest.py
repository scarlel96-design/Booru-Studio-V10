from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any


class ManifestValidationError(ValueError):
    """The capsule cannot be trusted or activated."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RESERVED = {
    "CON", "PRN", "AUX", "NUL", "CLOCK$",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_REQUIRED_ENTRYPOINTS = {"ui", "core", "worker", "supervisor"}


def _validate_relative_path(value: str) -> PureWindowsPath:
    if not value or "\x00" in value:
        raise ManifestValidationError("capsule file path is empty or contains NUL")
    path = PureWindowsPath(value)
    if path.is_absolute() or path.drive or any(part in {"", ".", ".."} for part in path.parts):
        raise ManifestValidationError(f"capsule path is not a safe relative path: {value!r}")
    for part in path.parts:
        stem = part.split(".", 1)[0].rstrip(" .").upper()
        if stem in _RESERVED or part.endswith((" ", ".")):
            raise ManifestValidationError(f"capsule path has a Windows-reserved component: {value!r}")
    return path


@dataclass(frozen=True, slots=True)
class CapsuleFile:
    path: str
    size: int
    sha256: str
    role: str

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "CapsuleFile":
        try:
            path, size, digest, role = raw["path"], raw["size"], raw["sha256"], raw["role"]
        except KeyError as exc:
            raise ManifestValidationError(f"capsule file is missing {exc.args[0]}") from exc
        if not isinstance(path, str) or not isinstance(role, str) or not isinstance(size, int):
            raise ManifestValidationError("capsule file has invalid field types")
        if size < 0 or not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ManifestValidationError(f"invalid digest or size for {path!r}")
        _validate_relative_path(path)
        return cls(path=path, size=size, sha256=digest, role=role)


@dataclass(frozen=True, slots=True)
class AppManifest:
    product: str
    version: str
    build: str
    capsule_id: str
    protocol: dict[str, int]
    db_schema: dict[str, int]
    release_sequence: int
    entrypoints: dict[str, str]
    files: tuple[CapsuleFile, ...]

    @classmethod
    def load(cls, path: Path) -> "AppManifest":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestValidationError(f"cannot load app manifest: {exc}") from exc
        if not isinstance(raw, dict):
            raise ManifestValidationError("app manifest root must be an object")
        try:
            manifest = cls(
                product=raw["product"], version=raw["version"], build=raw["build"],
                capsule_id=raw["capsule_id"], protocol=raw["protocol"],
                db_schema=raw["db_schema"], release_sequence=raw["release_sequence"],
                entrypoints=raw["entrypoints"],
                files=tuple(CapsuleFile.from_json(item) for item in raw["files"]),
            )
        except (KeyError, TypeError) as exc:
            raise ManifestValidationError("app manifest has an invalid shape") from exc
        manifest.validate_structure()
        return manifest

    def validate_structure(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.product, self.version, self.build, self.capsule_id)):
            raise ManifestValidationError("product, version, build, and capsule_id must be non-empty strings")
        if not isinstance(self.release_sequence, int) or self.release_sequence < 0:
            raise ManifestValidationError("release_sequence must be a non-negative integer")
        if set(self.entrypoints) != _REQUIRED_ENTRYPOINTS:
            raise ManifestValidationError("entrypoints must contain exactly ui/core/worker/supervisor")
        if not all(isinstance(value, int) and value >= 0 for value in self.protocol.values()):
            raise ManifestValidationError("protocol versions must be non-negative integers")
        if set(self.db_schema) != {"minimum", "maximum"} or self.db_schema["minimum"] > self.db_schema["maximum"]:
            raise ManifestValidationError("db_schema must have a valid minimum/maximum range")
        by_case: set[str] = set()
        declared: set[str] = set()
        for item in self.files:
            key = item.path.casefold()
            if key in by_case:
                raise ManifestValidationError(f"case-colliding capsule file: {item.path!r}")
            by_case.add(key)
            declared.add(item.path.replace("\\", "/"))
        if not self.files:
            raise ManifestValidationError("capsule manifest must declare files")
        for name, value in self.entrypoints.items():
            if not isinstance(value, str):
                raise ManifestValidationError(f"entrypoint {name} must be a string")
            normalized = _validate_relative_path(value).as_posix()
            if normalized not in declared:
                raise ManifestValidationError(f"entrypoint {name} is not a declared capsule file")

    def verify_capsule(self, root: Path) -> None:
        root = root.resolve(strict=True)
        declared = {item.path.replace("\\", "/"): item for item in self.files}
        observed: dict[str, Path] = {}
        for candidate in root.rglob("*"):
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                raise ManifestValidationError(f"symlink/reparse point forbidden in capsule: {relative}")
            if candidate.is_file():
                observed[relative] = candidate
        extras = sorted(set(observed) - set(declared) - {"app-manifest.json"})
        missing = sorted(set(declared) - set(observed))
        if extras or missing:
            raise ManifestValidationError(f"capsule inventory mismatch: missing={missing}, extra={extras}")
        for relative, item in declared.items():
            candidate = observed[relative]
            if candidate.stat().st_size != item.size:
                raise ManifestValidationError(f"capsule size mismatch: {relative}")
            with candidate.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            if digest != item.sha256:
                raise ManifestValidationError(f"capsule hash mismatch: {relative}")
