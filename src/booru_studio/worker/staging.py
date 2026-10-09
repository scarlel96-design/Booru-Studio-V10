from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from booru_studio.common.hashing import fsync_file, sha256_file
from booru_studio.common.paths import reject_symlink
from booru_studio.common.serialization import canonical_json_dumps
from booru_studio.domain.file_commit import CommitGrant, CommitResult, FileCommitStrategy


def _write_marker(path: Path, grant: CommitGrant) -> None:
    reject_symlink(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    reject_symlink(tmp)
    if tmp.exists():
        if not tmp.is_file():
            raise ValueError("commit marker temporary path is not a regular file")
        tmp.unlink()
    payload = canonical_json_dumps(
        {
            "commit_intent_id": str(grant.commit_intent_id),
            "artifact_id": str(grant.artifact_id),
            "size": grant.expected_size,
            "sha256": grant.expected_sha256.hex(),
        }
    ).encode("utf-8")
    with tmp.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def perform_commit(grant: CommitGrant) -> CommitResult:
    reject_symlink(grant.staging_path, allow_missing=False)
    reject_symlink(grant.final_path)
    reject_symlink(grant.marker_path)
    if not grant.staging_path.is_file():
        raise FileNotFoundError(grant.staging_path)
    if grant.final_path.exists():
        raise FileExistsError(grant.final_path)
    if grant.staging_path.stat().st_size != grant.expected_size:
        raise ValueError("staging size mismatch")
    if sha256_file(grant.staging_path) != grant.expected_sha256:
        raise ValueError("staging SHA-256 mismatch")

    fsync_file(grant.staging_path)
    grant.final_path.parent.mkdir(parents=True, exist_ok=True)
    marker_written = False
    if grant.strategy in (FileCommitStrategy.ATOMIC_RENAME, FileCommitStrategy.VERIFIED_RENAME):
        # The pre-existence check plus replace-free link/unlink is used to avoid overwriting.
        # On same-volume local filesystems this is equivalent to a no-replace promotion.
        os.link(grant.staging_path, grant.final_path)
        grant.staging_path.unlink()
    elif grant.strategy is FileCommitStrategy.COPY_VERIFY_COMMIT:
        with grant.staging_path.open("rb") as src, grant.final_path.open("xb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        _write_marker(grant.marker_path, grant)
        marker_written = True
    else:  # pragma: no cover
        raise ValueError(f"unsupported commit strategy: {grant.strategy}")
    fsync_file(grant.final_path)
    digest = sha256_file(grant.final_path)
    if grant.final_path.stat().st_size != grant.expected_size or digest != grant.expected_sha256:
        raise ValueError("final file verification failed")
    return CommitResult(
        commit_intent_id=grant.commit_intent_id,
        size_bytes=grant.expected_size,
        sha256=digest,
        marker_written=marker_written,
    )
