#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 2 ]; then
  printf 'usage: ROLLBACK.sh TARGET_DIR DIFF_FILE.patch\n' >&2
  exit 2
fi
target="$1"
patch="$2"
git -c core.autocrlf=false -C "$target" apply --reverse --check "$patch"
git -c core.autocrlf=false -C "$target" apply --reverse "$patch"
python3 -c 'from pathlib import Path; import sys; p=Path(sys.argv[1]); p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))' "$target/SOURCE_MANIFEST.sha256"
printf 'ROLLBACK_APPLIED\n'
