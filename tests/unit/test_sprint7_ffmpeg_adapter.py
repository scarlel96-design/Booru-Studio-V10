from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from booru_studio.common.errors import ErrorCode
from booru_studio.engine.adapters.ffmpeg import FfmpegAdapter, FfmpegEngineError


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg runtime unavailable")
def test_ffmpeg_merge_and_probe_are_verified_before_return(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.m4a"
    output = tmp_path / "merged.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10", "-t", "0.4", "-an",
        "-c:v", "mpeg4", "-q:v", "8", str(video),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "0.4", "-vn",
        "-c:a", "aac", str(audio),
    ], check=True)
    probe = FfmpegAdapter().merge_copy(
        video_path=video, audio_path=audio, output_path=output, cancel_event=threading.Event(),
    )
    assert output.is_file()
    assert probe.has_video and probe.has_audio


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg runtime unavailable")
def test_ffmpeg_failure_never_leaves_a_candidate_output(tmp_path: Path) -> None:
    bad_video = tmp_path / "bad-video.bin"; bad_video.write_bytes(b"not media")
    bad_audio = tmp_path / "bad-audio.bin"; bad_audio.write_bytes(b"not media")
    output = tmp_path / "should-not-exist.mp4"
    with pytest.raises(FfmpegEngineError) as caught:
        FfmpegAdapter().merge_copy(
            video_path=bad_video, audio_path=bad_audio, output_path=output, cancel_event=threading.Event(),
        )
    assert caught.value.error.code is ErrorCode.POSTPROCESS_FAILED
    assert not output.exists()
