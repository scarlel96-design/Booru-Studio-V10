from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.digest()


def fsync_file(path: Path) -> None:
    # Windows CRT rejects fsync on a read-only descriptor (EBADF). The file was
    # just staged by us and is writable; open it read/write before flushing.
    with path.open("r+b") as handle:
        import os
        os.fsync(handle.fileno())
