from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_FORBIDDEN = set('<>:"|?*')
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def normalize_relative_path(raw: str) -> str:
    if not raw or "\x00" in raw:
        raise ValueError("relative path is empty or contains NUL")
    raw = raw.replace("\\", "/")
    if raw.startswith("/") or raw.startswith("//") or _DRIVE_RE.match(raw):
        raise ValueError("absolute paths are forbidden")
    parts: list[str] = []
    for part in PurePosixPath(raw).parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("path traversal is forbidden")
        if part.endswith(" ") or part.endswith("."):
            raise ValueError("trailing spaces/dots are forbidden on Windows")
        if any(ch in _FORBIDDEN or ord(ch) < 32 for ch in part):
            raise ValueError("forbidden Windows filename character")
        stem = part.split(".", 1)[0].upper()
        if stem in _RESERVED:
            raise ValueError("reserved Windows device name")
        if ":" in part:
            raise ValueError("alternate data streams are forbidden")
        parts.append(part)
    if not parts:
        raise ValueError("relative path resolves to empty")
    normalized = "/".join(parts)
    if len(normalized) > 1024:
        raise ValueError("relative path is too long")
    return normalized


def resolve_contained(root: Path, relative: str) -> Path:
    normalized = normalize_relative_path(relative)
    root_abs = root.resolve()
    candidate = root_abs.joinpath(*normalized.split("/"))
    # lexical containment first; do not require candidate to exist
    common = os.path.commonpath([str(root_abs), str(candidate.absolute())])
    if os.path.normcase(common) != os.path.normcase(str(root_abs)):
        raise ValueError("path escapes storage root")
    return candidate


def reject_symlink(path: Path, *, allow_missing: bool = True) -> None:
    """Reject symlink components in the currently observable path chain.

    This is intentionally a source-layer check. Native Windows reparse-point/open-by-handle
    hardening remains a later Windows gate. Missing leaves are allowed when requested, but
    existing parent components are still inspected so a missing child beneath a symlinked
    directory cannot bypass containment.
    """
    try:
        if path.exists() or path.is_symlink():
            if path.is_symlink():
                raise ValueError(f"symlink path is not accepted: {path}")
        elif not allow_missing:
            raise FileNotFoundError(path)

        current = path if (path.exists() or path.is_symlink()) else path.parent
        while True:
            if current.is_symlink():
                raise ValueError(f"symlink component is not accepted: {current}")
            if current.parent == current:
                break
            current = current.parent
    except OSError as exc:
        raise ValueError(f"unable to validate path: {path}") from exc
