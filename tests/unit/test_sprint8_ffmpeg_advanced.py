from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from booru_studio.engine.adapters.ffmpeg import FfmpegAdapter


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg unavailable")
def test_remux_copy_preserves_media_and_verifies_output(tmp_path: Path) -> None:
    source = tmp_path / "source.mkv"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=64x48:rate=8",
        "-f", "lavfi", "-i", "sine=frequency=550:sample_rate=44100", "-t", "0.3",
        "-c:v", "mpeg4", "-q:v", "8", "-c:a", "aac", str(source),
    ], check=True)
    output = tmp_path / "remux.mp4"
    probe = FfmpegAdapter().remux_copy(
        input_path=source, output_path=output, cancel_event=threading.Event(), container_suffix=".mp4",
    )
    assert output.is_file() and output.stat().st_size > 0
    assert probe.has_video and probe.has_audio
