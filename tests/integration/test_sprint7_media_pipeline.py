from __future__ import annotations

import functools
import http.server
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from booru_studio.engine.adapters.yt_dlp import YtDlpAdapter
from booru_studio.engine.contracts import (
    CapabilityLevel, ExecutionCapabilityProfile, HandoffSafety, ManagedMediaExecutionPolicy,
    ManagedNetworkControlLevel, ManagedNetworkEnvelope, PauseSemantics, ResumeControl, RetryEnvelope,
)
from booru_studio.worker.media_pipeline import MediaWorkerPipeline


class NoopBackend:
    def probe_extractor(self, raw_input: str): return ("Generic", True)
    def extract(self, raw_input: str, *, flat_playlist: bool): raise AssertionError("not used")
    def download(self, *args, **kwargs): raise AssertionError("not used")


def policy() -> ManagedMediaExecutionPolicy:
    return ManagedMediaExecutionPolicy(
        ExecutionCapabilityProfile(
            CapabilityLevel.CONFIGURABLE, CapabilityLevel.CONFIGURABLE, CapabilityLevel.BEST_EFFORT,
            CapabilityLevel.CONFIGURABLE, PauseSemantics.RESTART_PHASE, ResumeControl.ENGINE_MANAGED,
            HandoffSafety.UNSAFE,
        ),
        ManagedNetworkEnvelope(2, ManagedNetworkControlLevel.CONFIGURABLE, 2, 2),
        RetryEnvelope(3, 2, 6),
    )


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg runtime unavailable")
def test_controlled_media_uses_direct_http_then_verified_ffmpeg(tmp_path: Path) -> None:
    origin = tmp_path / "origin"; origin.mkdir()
    video = origin / "video.mp4"
    audio = origin / "audio.m4a"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=80x60:rate=10", "-t", "0.5", "-an",
        "-c:v", "mpeg4", "-q:v", "8", str(video),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=44100", "-t", "0.5", "-vn",
        "-c:a", "aac", str(audio),
    ], check=True)

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(origin))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        adapter = YtDlpAdapter(NoopBackend())
        plan = adapter.plan_from_info({
            "id": "media-1", "extractor_key": "Test", "title": "Media", "ext": "mp4",
            "requested_formats": [
                {"url": f"{base}/video.mp4", "protocol": "http", "vcodec": "mpeg4", "acodec": "none", "ext": "mp4"},
                {"url": f"{base}/audio.m4a", "protocol": "http", "vcodec": "none", "acodec": "aac", "ext": "m4a"},
            ],
        }, raw_input=f"{base}/watch/1", policy=policy())
        staged = MediaWorkerPipeline(yt=adapter).execute_controlled(
            plan, work_dir=tmp_path / "work", cancel_event=threading.Event(),
        )
        assert staged.path.is_file()
        assert staged.size_bytes > 0
        assert len(staged.sha256) == 32
        assert staged.probe is not None and staged.probe.has_video and staged.probe.has_audio
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def _durable_media_setup(tmp_path: Path):
    from booru_studio.common.clock import ManualClock
    from booru_studio.common.ids import ClientInstanceId, CommandId, StorageTargetId
    from booru_studio.core.artifact_service import ArtifactService
    from booru_studio.core.job_service import JobService
    from booru_studio.domain.commands import CommandIdentity, CreateJobCommand
    from booru_studio.domain.enums import InputKind, JobKind
    from booru_studio.persistence.db_actor import DbActor

    clock = ManualClock(20_000, 0)
    actor = DbActor(tmp_path / "state" / "commit.sqlite3", now_utc_ms=clock.utc_ms()); actor.start()
    jobs = JobService(actor, clock)
    artifacts = ArtifactService(actor, clock)
    target = StorageTargetId.new()
    artifacts.register_storage_target(storage_target_id=target, generation=1, root=tmp_path / "final")
    created = jobs.create_job(CreateJobCommand(
        identity=CommandIdentity(ClientInstanceId.new(), CommandId.new()),
        input_kind=InputKind.URL,
        redacted_input="https://media.invalid/redacted",
        job_kind=JobKind.SINGLE_MEDIA,
        title="Sprint 7 media",
        storage_target_id=target,
        storage_target_generation=1,
    ))
    return actor, artifacts, created, target


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg runtime unavailable")
def test_controlled_media_verified_output_enters_existing_crash_safe_file_commit(tmp_path: Path) -> None:
    from booru_studio.worker.staging import perform_commit

    origin = tmp_path / "origin2"; origin.mkdir()
    video = origin / "video.mp4"; audio = origin / "audio.m4a"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=64x48:rate=8", "-t", "0.4", "-an",
        "-c:v", "mpeg4", "-q:v", "8", str(video),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "0.4", "-vn",
        "-c:a", "aac", str(audio),
    ], check=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(origin))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    actor, artifacts, created, target = _durable_media_setup(tmp_path)
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        adapter = YtDlpAdapter(NoopBackend())
        plan = adapter.plan_from_info({
            "id": "commit-1", "extractor_key": "Test", "title": "Committed", "ext": "mkv",
            "requested_formats": [
                {"url": f"{base}/video.mp4", "protocol": "http", "vcodec": "mpeg4", "acodec": "none", "ext": "mp4"},
                {"url": f"{base}/audio.m4a", "protocol": "http", "vcodec": "none", "acodec": "aac", "ext": "m4a"},
            ],
        }, raw_input=f"{base}/watch/1", policy=policy())
        artifact_plan = artifacts.plan_artifact(
            job_id=created.job_id, storage_target_id=target, storage_generation=1,
            relative_path="영상/merged.mkv",
        )
        staged = MediaWorkerPipeline(yt=adapter).execute_controlled(
            plan,
            work_dir=tmp_path / "controlled-work",
            output_path=artifact_plan.staging_path,
            cancel_event=threading.Event(),
        )
        assert staged.path == artifact_plan.staging_path
        grant = artifacts.prepare_commit(artifact_id=artifact_plan.artifact_id)
        finalized = artifacts.finalize_commit(perform_commit(grant))
        assert finalized.committed_state_revision > 0
        assert artifact_plan.final_path.is_file()
        assert artifact_plan.final_path.read_bytes() != b""
        assert not artifact_plan.staging_path.exists()
        assert actor.submit(lambda c: c.execute(
            "SELECT COUNT(*) FROM file_records WHERE artifact_id=?", (str(artifact_plan.artifact_id),)
        ).fetchone()[0]).result(2) == 1
    finally:
        actor.close(); server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_simple_media_uses_core_artifact_identity_in_resume_sidecar_and_commits(tmp_path: Path) -> None:
    from booru_studio.worker.staging import perform_commit

    body = b"sprint7-simple-direct" * 2048
    origin = tmp_path / "origin3"; origin.mkdir(); (origin / "media.mp4").write_bytes(body)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(origin))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    actor, artifacts, created, target = _durable_media_setup(tmp_path)
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        adapter = YtDlpAdapter(NoopBackend())
        plan = adapter.plan_from_info({
            "id": "simple-1", "extractor_key": "Test", "title": "Simple", "ext": "mp4",
            "url": f"{base}/media.mp4", "protocol": "http", "vcodec": "h264", "acodec": "aac",
            "filesize": len(body),
        }, raw_input=f"{base}/watch/simple", policy=policy())
        artifact_plan = artifacts.plan_artifact(
            job_id=created.job_id, storage_target_id=target, storage_generation=1,
            relative_path="영상/simple.mp4", expected_size=len(body),
        )
        staged = MediaWorkerPipeline(yt=adapter).execute_simple_direct(
            plan,
            work_dir=tmp_path / "simple-work",
            staging_path=artifact_plan.staging_path,
            artifact_id=artifact_plan.artifact_id,
            generation=1,
            cancel_event=threading.Event(),
        )
        assert staged.sidecar_path is not None
        mirrored = artifacts.register_resume_sidecar(staged.sidecar_path)
        assert mirrored.artifact_id == artifact_plan.artifact_id
        grant = artifacts.prepare_commit(artifact_id=artifact_plan.artifact_id)
        artifacts.finalize_commit(perform_commit(grant))
        assert artifact_plan.final_path.read_bytes() == body
    finally:
        actor.close(); server.shutdown(); server.server_close(); thread.join(timeout=2)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg runtime unavailable")
def test_controlled_postprocess_failure_cannot_create_file_record(tmp_path: Path) -> None:
    origin = tmp_path / "origin4"; origin.mkdir()
    video = origin / "video.mp4"; bad_audio = origin / "audio.m4a"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=64x48:rate=8", "-t", "0.3", "-an",
        "-c:v", "mpeg4", "-q:v", "8", str(video),
    ], check=True)
    bad_audio.write_bytes(b"not-a-media-stream")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(origin))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    actor, artifacts, created, target = _durable_media_setup(tmp_path)
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        adapter = YtDlpAdapter(NoopBackend())
        plan = adapter.plan_from_info({
            "id": "bad-merge", "extractor_key": "Test", "title": "Bad", "ext": "mkv",
            "requested_formats": [
                {"url": f"{base}/video.mp4", "protocol": "http", "vcodec": "mpeg4", "acodec": "none", "ext": "mp4"},
                {"url": f"{base}/audio.m4a", "protocol": "http", "vcodec": "none", "acodec": "aac", "ext": "m4a"},
            ],
        }, raw_input=f"{base}/watch/bad", policy=policy())
        artifact_plan = artifacts.plan_artifact(
            job_id=created.job_id, storage_target_id=target, storage_generation=1,
            relative_path="영상/bad.mkv",
        )
        with pytest.raises(Exception):
            MediaWorkerPipeline(yt=adapter).execute_controlled(
                plan,
                work_dir=tmp_path / "bad-work",
                output_path=artifact_plan.staging_path,
                cancel_event=threading.Event(),
            )
        assert not artifact_plan.staging_path.exists()
        assert not artifact_plan.final_path.exists()
        counts = actor.submit(lambda c: (
            c.execute("SELECT COUNT(*) FROM file_records WHERE artifact_id=?", (str(artifact_plan.artifact_id),)).fetchone()[0],
            c.execute("SELECT COUNT(*) FROM file_commit_intents WHERE artifact_id=?", (str(artifact_plan.artifact_id),)).fetchone()[0],
        )).result(2)
        assert counts == (0, 0)
    finally:
        actor.close(); server.shutdown(); server.server_close(); thread.join(timeout=2)
