from __future__ import annotations

import shutil
import sys
from importlib.metadata import version

from booru_studio.engine.adapters.ffmpeg import FfmpegAdapter
from booru_studio.engine.adapters.yt_dlp import (
    DENO_MIN_VERSION, YT_DLP_EJS_PIN, YT_DLP_PIN, YtDlpPythonBackend,
)


def main() -> int:
    installed = version("yt-dlp")
    ejs = version("yt-dlp-ejs")
    YtDlpPythonBackend._verify_runtime(require_javascript=True)
    backend = YtDlpPythonBackend()
    # Network-free extractor registry smoke. Generic matching is acceptable here; this verifies that
    # the pinned package can be imported and the extractor registry can be instantiated.
    probe = backend.probe_extractor("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    if probe is None:
        raise RuntimeError("yt-dlp extractor registry did not match a canonical YouTube URL")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg/ffprobe are required for Sprint 7 runtime smoke")
    ffmpeg_version, ffprobe_version = FfmpegAdapter().runtime_gate()
    print(f"yt-dlp={installed} expected={YT_DLP_PIN} extractor={probe[0]}")
    print(f"yt-dlp-ejs={ejs} expected={YT_DLP_EJS_PIN} deno-min={'.'.join(map(str, DENO_MIN_VERSION))}")
    print(ffmpeg_version)
    print(ffprobe_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
