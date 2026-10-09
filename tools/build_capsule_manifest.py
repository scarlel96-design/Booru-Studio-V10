from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the immutable App Capsule inventory.")
    parser.add_argument("capsule_root", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--build", required=True)
    parser.add_argument("--capsule-id", required=True)
    parser.add_argument("--entrypoint", action="append", default=[], metavar="NAME=PATH")
    args = parser.parse_args(argv)
    root = args.capsule_root.resolve()
    entrypoints = dict(item.split("=", 1) for item in args.entrypoint)
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "app-manifest.json":
            continue
        relative = path.relative_to(root).as_posix()
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        files.append({"path": relative, "size": path.stat().st_size, "sha256": digest, "role": "runtime"})
    payload = {
        "product": "Booru Studio", "version": args.version, "build": args.build,
        "capsule_id": args.capsule_id, "protocol": {"ui_core": 1, "core_worker": 1},
        "db_schema": {"minimum": 1, "maximum": 1}, "release_sequence": 0,
        "entrypoints": entrypoints, "files": files,
    }
    (root / "app-manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
