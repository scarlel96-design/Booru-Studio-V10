from __future__ import annotations

import threading
from pathlib import Path

import pytest

from booru_studio.domain.presentation import CollectionSemantics, PresentationMode
from booru_studio.engine.adapters.yt_dlp import (
    MediaExecutionMode,
    ManagedDownloadResult,
    YtDlpAdapter,
    YtDlpCancelled,
    YtDlpPythonBackend,
    options_from_policy,
)
from booru_studio.engine.contracts import (
    CapabilityLevel,
    ExecutionCapabilityProfile,
    HandoffSafety,
    ManagedMediaExecutionPolicy,
    ManagedNetworkControlLevel,
    ManagedNetworkEnvelope,
    PauseSemantics,
    ResumeControl,
    RetryEnvelope,
)


def policy(level: ManagedNetworkControlLevel = ManagedNetworkControlLevel.CONFIGURABLE) -> ManagedMediaExecutionPolicy:
    grant = None if level is ManagedNetworkControlLevel.OPAQUE else 2
    return ManagedMediaExecutionPolicy(
        capabilities=ExecutionCapabilityProfile(
            transfer_control=CapabilityLevel.CONFIGURABLE,
            network_parallelism_control=CapabilityLevel.CONFIGURABLE,
            progress_control=CapabilityLevel.BEST_EFFORT,
            postprocess_control=CapabilityLevel.CONFIGURABLE,
            pause_semantics=PauseSemantics.RESTART_PHASE,
            resume_control=ResumeControl.ENGINE_MANAGED,
            direct_handoff=HandoffSafety.UNSAFE,
        ),
        network=ManagedNetworkEnvelope(
            requested_parallelism=4,
            granted_parallelism=grant,
            admission_weight=4 if grant is None else 2,
            control_level=level,
        ),
        retry=RetryEnvelope(outer_episode_attempt_limit=3, inner_operation_attempt_limit=2, hard_compound_attempt_ceiling=6),
    )


class FakeBackend:
    def __init__(self, flat, full=None):
        self.flat = flat
        self.full = full if full is not None else flat
        self.download_calls = []

    def probe_extractor(self, raw_input: str):
        return ("Youtube", False) if "youtube" in raw_input else ("Generic", True)

    def extract(self, raw_input: str, *, flat_playlist: bool):
        return self.flat if flat_playlist else self.full

    def download(self, raw_input: str, *, output_dir: Path, options, cancel_event: threading.Event):
        self.download_calls.append((raw_input, output_dir, dict(options)))
        if cancel_event.is_set():
            raise YtDlpCancelled("cancelled")
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / "ok.mp4"
        out.write_bytes(b"ok")
        return ManagedDownloadResult((out,), {"id": "ok"})


def test_single_media_is_never_synthetic_batch_and_metadata_is_allowlisted() -> None:
    info = {
        "id": "abc123", "extractor_key": "Youtube", "title": "One video",
        "uploader": "tester", "duration": 12.5, "webpage_url": "https://youtube.test/watch?v=abc123&token=SECRET",
        "http_headers": {"Cookie": "SECRET_COOKIE"}, "formats": [{"url": "https://cdn/?sig=SECRET"}],
    }
    result = YtDlpAdapter(FakeBackend(info)).discover("https://youtube.test/watch?v=abc123&token=INPUT_SECRET")
    assert result.presentation.mode is PresentationMode.INDIVIDUAL
    assert result.presentation.collection is CollectionSemantics.NONE
    assert result.items[0].source_identity == "media:youtube:abc123"
    rendered = repr(dict(result.items[0].sanitized_metadata))
    assert "SECRET" not in rendered
    assert "webpage_url" not in rendered
    assert "http_headers" not in rendered
    assert "formats" not in rendered


def test_playlist_lazy_count_and_missing_index_preserve_stable_identity() -> None:
    playlist = {
        "_type": "playlist", "id": "PL-1", "extractor_key": "YoutubeTab", "title": "List",
        "entries": [
            {"id": "v1", "extractor_key": "Youtube", "title": "A"},
            {"id": "v2", "extractor_key": "Youtube", "title": "B"},
        ],
    }
    result = YtDlpAdapter(FakeBackend(playlist)).discover("https://youtube.test/playlist?list=PL-1&token=SECRET")
    assert result.presentation.mode is PresentationMode.BATCH
    assert result.presentation.collection is CollectionSemantics.PLAYLIST
    assert result.reported_count is None
    assert result.completeness == "PARTIAL"
    assert [item.source_identity for item in result.items] == ["media:youtube:v1", "media:youtube:v2"]
    assert [item.source_index for item in result.items] == [0, 1]


def test_channel_is_batch_semantic_without_requiring_total_count() -> None:
    channel = {
        "_type": "playlist", "id": "UC1", "extractor_key": "YoutubeTab", "title": "Channel",
        "webpage_url": "https://www.youtube.com/@example/videos",
        "entries": [{"id": "v1", "extractor_key": "Youtube", "title": "A"}],
    }
    result = YtDlpAdapter(FakeBackend(channel)).discover("https://www.youtube.com/@example/videos")
    assert result.presentation.collection is CollectionSemantics.CHANNEL
    assert result.presentation.mode is PresentationMode.BATCH


def test_simple_direct_and_controlled_media_planning_are_truthful() -> None:
    adapter = YtDlpAdapter(FakeBackend({}))
    direct = adapter.plan_from_info({
        "id": "d1", "extractor_key": "X", "title": "Direct", "ext": "mp4",
        "url": "https://cdn.test/d.mp4", "protocol": "https", "vcodec": "h264", "acodec": "aac",
    }, raw_input="https://site.test/d1", policy=policy())
    assert direct.mode == MediaExecutionMode.SIMPLE_DIRECT
    assert direct.capabilities.transfer_control is CapabilityLevel.EXACT
    assert direct.candidate_artifacts[0].descriptor.handoff_safety is HandoffSafety.SAFE

    controlled = adapter.plan_from_info({
        "id": "c1", "extractor_key": "X", "title": "Controlled", "ext": "mp4",
        "requested_formats": [
            {"url": "https://cdn.test/v.mp4?sig=abc", "protocol": "https", "vcodec": "h264", "acodec": "none", "ext": "mp4"},
            {"url": "https://cdn.test/a.m4a", "protocol": "https", "vcodec": "none", "acodec": "aac", "ext": "m4a"},
        ],
    }, raw_input="https://site.test/c1", policy=policy())
    assert controlled.mode == MediaExecutionMode.CONTROLLED_MEDIA
    assert {c.role for c in controlled.candidate_artifacts} == {"VIDEO", "AUDIO"}
    assert controlled.capabilities.postprocess_control is CapabilityLevel.EXACT


def test_secret_or_fragment_bound_formats_fall_back_to_compat_without_false_exactness() -> None:
    adapter = YtDlpAdapter(FakeBackend({}))
    result = adapter.plan_from_info({
        "id": "x", "extractor_key": "X", "title": "HLS", "ext": "mp4",
        "requested_formats": [{
            "url": "https://cdn.test/master.m3u8?token=SECRET", "protocol": "m3u8_native",
            "vcodec": "h264", "acodec": "aac", "fragments": [{"url": "seg.ts"}],
            "http_headers": {"Cookie": "session=SECRET"},
        }],
    }, raw_input="https://site.test/x", policy=policy(ManagedNetworkControlLevel.BEST_EFFORT))
    assert result.mode == MediaExecutionMode.COMPAT_MEDIA
    assert result.capabilities.network_parallelism_control is CapabilityLevel.BEST_EFFORT
    assert result.capabilities.direct_handoff is HandoffSafety.UNSAFE


def test_retry_policy_maps_to_finite_yt_dlp_knobs_and_opaque_does_not_claim_concurrency() -> None:
    options = dict(options_from_policy(policy()))
    assert options["retries"] == 1
    assert options["fragment_retries"] == 1
    assert options["extractor_retries"] == 1
    assert options["concurrent_fragment_downloads"] == 2
    assert all(value != "infinite" for value in options.values())

    opaque = dict(options_from_policy(policy(ManagedNetworkControlLevel.OPAQUE)))
    assert "concurrent_fragment_downloads" not in opaque


def test_cancelled_managed_execution_does_not_poison_next_execution(tmp_path: Path) -> None:
    backend = FakeBackend({"id": "x"})
    adapter = YtDlpAdapter(backend)
    cancelled = threading.Event(); cancelled.set()
    with pytest.raises(YtDlpCancelled):
        adapter.execute_compat("https://site.test/x", output_dir=tmp_path / "first", policy=policy(), cancel_event=cancelled)
    fresh = threading.Event()
    result = adapter.execute_compat("https://site.test/x", output_dir=tmp_path / "second", policy=policy(), cancel_event=fresh)
    assert result.output_paths[0].read_bytes() == b"ok"



def test_python_backend_disables_remote_executable_components() -> None:
    options = YtDlpPythonBackend._base_options()
    assert options["remote_components"] == set()
    assert "exec" not in options
    assert "external_downloader" not in options


def test_javascript_runtime_gate_requires_pinned_ejs_and_supported_deno(monkeypatch) -> None:
    import booru_studio.engine.adapters.yt_dlp.adapter as module

    versions = {"yt-dlp": "2026.08.19", "yt-dlp-ejs": "0.8.0"}
    monkeypatch.setattr(module, "version", lambda name: versions[name])
    monkeypatch.setattr(module.shutil, "which", lambda name: "/engine/deno" if name == "deno" else None)

    class Probe:
        returncode = 0
        stdout = "deno 2.8.3\nv8 14.2\ntypescript 5.9\n"
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Probe())
    YtDlpPythonBackend._verify_runtime(require_javascript=True)

    versions["yt-dlp-ejs"] = "0.7.0"
    with pytest.raises(Exception, match="yt-dlp-ejs version mismatch"):
        YtDlpPythonBackend._verify_runtime(require_javascript=True)

    versions["yt-dlp-ejs"] = "0.8.0"
    class OldProbe(Probe):
        stdout = "deno 2.2.9\n"
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: OldProbe())
    with pytest.raises(Exception, match="below the supported floor"):
        YtDlpPythonBackend._verify_runtime(require_javascript=True)


def test_media_worker_compat_path_accepts_only_regular_outputs_inside_worker_directory(tmp_path: Path) -> None:
    from booru_studio.worker.media_pipeline import MediaWorkerPipeline

    backend = FakeBackend({"id": "managed", "extractor_key": "X", "title": "Managed"})
    adapter = YtDlpAdapter(backend)
    plan = adapter.plan_from_info(
        {
            "id": "managed", "extractor_key": "X", "title": "Managed", "ext": "mp4",
            "requested_formats": [{
                "url": "https://cdn.test/master.m3u8", "protocol": "m3u8_native",
                "vcodec": "h264", "acodec": "aac", "fragments": [{"url": "seg.ts"}],
            }],
        },
        raw_input="https://site.test/managed",
        policy=policy(),
    )
    outputs = MediaWorkerPipeline(yt=adapter).execute_compat(
        plan,
        raw_input="https://site.test/managed",
        output_dir=tmp_path / "managed",
        policy=policy(),
        cancel_event=threading.Event(),
    )
    assert len(outputs) == 1
    assert outputs[0].path.read_bytes() == b"ok"


def test_media_worker_rejects_managed_output_path_escape(tmp_path: Path) -> None:
    from booru_studio.worker.media_pipeline import MediaWorkerPipeline

    class EscapeBackend(FakeBackend):
        def download(self, raw_input: str, *, output_dir: Path, options, cancel_event: threading.Event):
            outside = output_dir.parent / "outside.mp4"
            outside.write_bytes(b"escape")
            return ManagedDownloadResult((outside,), {"id": "escape"})

    adapter = YtDlpAdapter(EscapeBackend({"id": "escape"}))
    plan = adapter.plan_from_info(
        {"id": "escape", "extractor_key": "X", "title": "Escape", "ext": "mp4"},
        raw_input="https://site.test/escape",
        policy=policy(),
    )
    assert plan.mode == MediaExecutionMode.COMPAT_MEDIA
    with pytest.raises(ValueError, match="escaped"):
        MediaWorkerPipeline(yt=adapter).execute_compat(
            plan,
            raw_input="https://site.test/escape",
            output_dir=tmp_path / "managed",
            policy=policy(),
            cancel_event=threading.Event(),
        )
