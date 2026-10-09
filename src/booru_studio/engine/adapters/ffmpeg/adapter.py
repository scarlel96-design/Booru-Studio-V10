from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from booru_studio.common.errors import ErrorCode, ErrorConfidence, ErrorInstance


class FfmpegEngineError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.error = ErrorInstance(
            code=code,
            confidence=ErrorConfidence.STRONG,
            user_message_key=f"error.{code.value.lower()}",
            retryable=False,
        )


class FfmpegCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MediaProbe:
    format_name: str
    duration_s: float | None
    streams: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "streams", tuple(MappingProxyType(dict(row)) for row in self.streams))

    @property
    def has_video(self) -> bool:
        return any(stream.get("codec_type") == "video" for stream in self.streams)

    @property
    def has_audio(self) -> bool:
        return any(stream.get("codec_type") == "audio" for stream in self.streams)


class FfmpegAdapter:
    """Minimal Sprint-7 FFmpeg/ffprobe boundary: stream-copy merge and structural probe only."""

    def __init__(self, ffmpeg: str | None = None, ffprobe: str | None = None) -> None:
        self.ffmpeg = ffmpeg or shutil.which("ffmpeg") or "ffmpeg"
        self.ffprobe = ffprobe or shutil.which("ffprobe") or "ffprobe"

    def runtime_gate(self) -> tuple[str, str]:
        return self._version(self.ffmpeg), self._version(self.ffprobe)

    @staticmethod
    def _version(executable: str) -> str:
        try:
            result = subprocess.run(
                [executable, "-version"], capture_output=True, text=True, timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise FfmpegEngineError(ErrorCode.ENGINE_UNAVAILABLE, "FFmpeg runtime is unavailable") from exc
        if result.returncode != 0:
            raise FfmpegEngineError(ErrorCode.ENGINE_UNAVAILABLE, "FFmpeg runtime probe failed")
        first = (result.stdout or result.stderr).splitlines()
        if not first:
            raise FfmpegEngineError(ErrorCode.ENGINE_PROTOCOL_ERROR, "FFmpeg version output is empty")
        return first[0][:240]

    def probe(self, path: Path) -> MediaProbe:
        if not path.is_file():
            raise FfmpegEngineError(ErrorCode.VERIFICATION_FAILED, "media probe input does not exist")
        command = [
            self.ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise FfmpegEngineError(ErrorCode.ENGINE_UNAVAILABLE, "ffprobe execution failed") from exc
        if result.returncode != 0:
            raise FfmpegEngineError(ErrorCode.VERIFICATION_FAILED, "ffprobe rejected staged media")
        try:
            payload = json.loads(result.stdout)
        except (TypeError, ValueError) as exc:
            raise FfmpegEngineError(ErrorCode.ENGINE_PROTOCOL_ERROR, "ffprobe returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise FfmpegEngineError(ErrorCode.ENGINE_PROTOCOL_ERROR, "ffprobe JSON root is invalid")
        raw_streams = payload.get("streams") or []
        if not isinstance(raw_streams, list):
            raise FfmpegEngineError(ErrorCode.ENGINE_PROTOCOL_ERROR, "ffprobe streams are invalid")
        streams: list[dict[str, object]] = []
        for row in raw_streams[:64]:
            if not isinstance(row, dict):
                continue
            safe: dict[str, object] = {}
            for key in ("index", "codec_name", "codec_type", "width", "height", "sample_rate", "channels"):
                value = row.get(key)
                if isinstance(value, (str, int, float, bool)) or value is None:
                    safe[key] = value
            streams.append(safe)
        raw_format = payload.get("format") or {}
        if not isinstance(raw_format, dict):
            raw_format = {}
        duration: float | None = None
        try:
            if raw_format.get("duration") not in (None, ""):
                duration = float(raw_format["duration"])
        except (TypeError, ValueError):
            duration = None
        return MediaProbe(
            format_name=str(raw_format.get("format_name") or "")[:120],
            duration_s=duration,
            streams=tuple(streams),
        )


    def remux_copy(
        self,
        *,
        input_path: Path,
        output_path: Path,
        cancel_event: threading.Event,
        container_suffix: str | None = None,
    ) -> MediaProbe:
        """Container-only remux with no transcoding and structural verification."""
        if not input_path.is_file():
            raise FfmpegEngineError(ErrorCode.POSTPROCESS_FAILED, "remux input is missing")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = (container_suffix or output_path.suffix).lower()
        if suffix and not suffix.startswith("."):
            suffix = "." + suffix
        if suffix in {"", ".part", ".tmp"} or not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
            raise FfmpegEngineError(ErrorCode.POSTPROCESS_FAILED, "remux container suffix is invalid")
        temp = output_path.with_name(f"{output_path.stem}.ffmpeg-remux{suffix}")
        temp.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        command = [
            self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(input_path), "-map", "0", "-c", "copy", str(temp),
        ]
        try:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        except OSError as exc:
            raise FfmpegEngineError(ErrorCode.ENGINE_UNAVAILABLE, "ffmpeg could not be started") from exc
        try:
            while process.poll() is None:
                if cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=3)
                    raise FfmpegCancelled("FFmpeg cancellation requested")
                time.sleep(0.02)
            if process.returncode != 0:
                raise FfmpegEngineError(ErrorCode.POSTPROCESS_FAILED, f"ffmpeg remux failed with exit code {process.returncode}")
            os.replace(temp, output_path)
            probe = self.probe(output_path)
            if not (probe.has_video or probe.has_audio):
                output_path.unlink(missing_ok=True)
                raise FfmpegEngineError(ErrorCode.VERIFICATION_FAILED, "remuxed media contains no audio/video stream")
            return probe
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=3)
            temp.unlink(missing_ok=True)
            if process.returncode not in (0, None):
                output_path.unlink(missing_ok=True)

    def merge_copy(
        self,
        *,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
        cancel_event: threading.Event,
        container_suffix: str | None = None,
    ) -> MediaProbe:
        if not video_path.is_file() or not audio_path.is_file():
            raise FfmpegEngineError(ErrorCode.POSTPROCESS_FAILED, "merge input is missing")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = (container_suffix or output_path.suffix).lower()
        if suffix and not suffix.startswith("."):
            suffix = "." + suffix
        if suffix in {"", ".part", ".tmp"}:
            raise FfmpegEngineError(
                ErrorCode.POSTPROCESS_FAILED,
                "postprocess container suffix is required for extensionless staging paths",
            )
        if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
            raise FfmpegEngineError(ErrorCode.POSTPROCESS_FAILED, "postprocess container suffix is invalid")
        temp = output_path.with_name(f"{output_path.stem}.ffmpeg-tmp{suffix}")
        temp.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        command = [
            self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(video_path), "-i", str(audio_path),
            "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", str(temp),
        ]
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            )
        except OSError as exc:
            raise FfmpegEngineError(ErrorCode.ENGINE_UNAVAILABLE, "ffmpeg could not be started") from exc
        try:
            while process.poll() is None:
                if cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                    raise FfmpegCancelled("FFmpeg cancellation requested")
                time.sleep(0.02)
            stderr = process.stderr.read() if process.stderr is not None else ""
            if process.returncode != 0:
                raise FfmpegEngineError(
                    ErrorCode.POSTPROCESS_FAILED,
                    f"ffmpeg merge failed with exit code {process.returncode}",
                )
            os.replace(temp, output_path)
            probe = self.probe(output_path)
            if not probe.has_video or not probe.has_audio:
                output_path.unlink(missing_ok=True)
                raise FfmpegEngineError(ErrorCode.VERIFICATION_FAILED, "merged media lacks audio/video streams")
            return probe
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
            temp.unlink(missing_ok=True)
            if process.returncode not in (0, None):
                output_path.unlink(missing_ok=True)
