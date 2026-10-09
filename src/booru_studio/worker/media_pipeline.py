from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from pathlib import Path

from booru_studio.common.hashing import sha256_file
from booru_studio.common.ids import ArtifactId
from booru_studio.common.paths import reject_symlink
from booru_studio.worker.execution_plane import DirectHttpExecutionPlane
from booru_studio.engine.adapters.ffmpeg import FfmpegAdapter, MediaProbe
from booru_studio.engine.adapters.yt_dlp import (
    MediaDiscoveryResult,
    MediaExecutionMode,
    MediaExecutionPlan,
    YtDlpAdapter,
)
from booru_studio.engine.contracts import CandidateArtifact, HandoffSafety, ManagedMediaExecutionPolicy


@dataclass(frozen=True, slots=True)
class MediaDiscoveryBatch:
    sequence: int
    items: tuple

    def __post_init__(self) -> None:
        if self.sequence < 0 or not self.items:
            raise ValueError("invalid media discovery batch")


@dataclass(frozen=True, slots=True)
class MediaWorkerDiscovery:
    source_kind: str
    presentation: object
    batches: tuple[MediaDiscoveryBatch, ...]
    collection_identity: str | None
    collection_title: str | None
    reported_count: int | None
    completeness: str

    @property
    def item_count(self) -> int:
        return sum(len(batch.items) for batch in self.batches)


@dataclass(frozen=True, slots=True)
class StagedMediaArtifact:
    path: Path
    size_bytes: int
    sha256: bytes
    probe: MediaProbe | None = None
    sidecar_path: Path | None = None


class MediaWorkerPipeline:
    """Worker-owned yt-dlp/DirectHTTP/FFmpeg orchestration for Sprint 7."""

    _MAX_BATCH = 500

    def __init__(
        self,
        yt: YtDlpAdapter | None = None,
        ffmpeg: FfmpegAdapter | None = None,
        direct: DirectHttpExecutionPlane | None = None,
    ) -> None:
        self._yt = yt or YtDlpAdapter()
        self._ffmpeg = ffmpeg or FfmpegAdapter()
        self._direct = direct or DirectHttpExecutionPlane()

    def discover(self, raw_input: str, *, batch_size: int = 250) -> MediaWorkerDiscovery:
        if not 1 <= batch_size <= self._MAX_BATCH:
            raise ValueError(f"media batch_size must be between 1 and {self._MAX_BATCH}")
        result: MediaDiscoveryResult = self._yt.discover(raw_input)
        batches = tuple(
            MediaDiscoveryBatch(sequence=i, items=tuple(result.items[start:start + batch_size]))
            for i, start in enumerate(range(0, len(result.items), batch_size))
        )
        return MediaWorkerDiscovery(
            source_kind=result.source_kind,
            presentation=result.presentation,
            batches=batches,
            collection_identity=result.collection_identity,
            collection_title=result.collection_title,
            reported_count=result.reported_count,
            completeness=result.completeness,
        )

    def resolve(self, raw_input: str, policy: ManagedMediaExecutionPolicy) -> MediaExecutionPlan:
        return self._yt.resolve(raw_input, policy)

    @staticmethod
    def _wire(
        candidate: CandidateArtifact, *, staging_path: Path,
        artifact_id: ArtifactId | None = None, generation: int = 0,
    ) -> dict[str, object]:
        descriptor = candidate.descriptor
        if descriptor.handoff_safety is HandoffSafety.UNSAFE:
            raise ValueError("UNSAFE media descriptor cannot enter DirectHTTP")
        headers = dict(descriptor.headers)
        if descriptor.referer and not any(k.casefold() == "referer" for k in headers):
            headers["Referer"] = descriptor.referer
        return {
            "artifact_id": str(artifact_id or ArtifactId.new()),
            "generation": generation,
            "url": descriptor.url,
            "headers": headers,
            "staging_path": str(staging_path),
            "sidecar_path": str(staging_path.with_suffix(staging_path.suffix + ".resume.json")),
            "source_fingerprint": hashlib.sha256(descriptor.url.encode("utf-8")).hexdigest(),
            "expected_size": descriptor.expected_size,
            "expected_sha256": None,
            "redirect_policy": descriptor.redirect_policy,
            "network_scope_policy": descriptor.network_scope_policy,
            "network_scope_root": descriptor.network_scope_root,
            "timeout_s": 30.0,
            "retry_ceiling": 2,
        }

    def execute_simple_direct(
        self,
        plan: MediaExecutionPlan,
        *,
        work_dir: Path,
        cancel_event: threading.Event,
        staging_path: Path | None = None,
        artifact_id: ArtifactId | None = None,
        generation: int = 0,
    ) -> StagedMediaArtifact:
        if plan.mode != MediaExecutionMode.SIMPLE_DIRECT or len(plan.candidate_artifacts) != 1:
            raise ValueError("simple-direct execution requires exactly one candidate")
        work_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(plan.output_filename).suffix or ".bin"
        staging = staging_path or (work_dir / f"simple{suffix}.part")
        staging.parent.mkdir(parents=True, exist_ok=True)
        candidate = plan.candidate_artifacts[0]
        result_box: list[dict[str, object]] = []
        self._direct.run(
            {"mode": "DIRECT_HTTP", "parallelism": 1, "transfers": [self._wire(
                candidate, staging_path=staging, artifact_id=artifact_id, generation=generation,
            )]},
            cancel_event=cancel_event,
            on_staged=result_box.append,
        )
        if len(result_box) != 1 or not staging.is_file():
            raise RuntimeError("DirectHTTP did not produce the expected staged media")
        sidecar = Path(str(result_box[0]["sidecar_path"])) if result_box[0].get("sidecar_path") else None
        return StagedMediaArtifact(staging, staging.stat().st_size, sha256_file(staging), sidecar_path=sidecar)

    def execute_controlled(
        self,
        plan: MediaExecutionPlan,
        *,
        work_dir: Path,
        cancel_event: threading.Event,
        output_path: Path | None = None,
    ) -> StagedMediaArtifact:
        if plan.mode != MediaExecutionMode.CONTROLLED_MEDIA:
            raise ValueError("controlled execution requires CONTROLLED_MEDIA plan")
        by_role = {candidate.role: candidate for candidate in plan.candidate_artifacts}
        if set(by_role) != {"VIDEO", "AUDIO"}:
            raise ValueError("controlled media requires VIDEO and AUDIO candidates")
        work_dir.mkdir(parents=True, exist_ok=True)
        video_path = work_dir / "video.input"
        audio_path = work_dir / "audio.input"
        transfers = [
            self._wire(by_role["VIDEO"], staging_path=video_path),
            self._wire(by_role["AUDIO"], staging_path=audio_path),
        ]
        self._direct.run(
            {"mode": "DIRECT_HTTP", "parallelism": 2, "transfers": transfers},
            cancel_event=cancel_event,
        )
        if cancel_event.is_set():
            raise RuntimeError("controlled media cancelled before postprocess")
        suffix = Path(plan.output_filename).suffix or ".mkv"
        output = output_path or (work_dir / f"merged.staged{suffix}")
        output.parent.mkdir(parents=True, exist_ok=True)
        probe = self._ffmpeg.merge_copy(
            video_path=video_path,
            audio_path=audio_path,
            output_path=output,
            cancel_event=cancel_event,
            container_suffix=suffix,
        )
        if not output.is_file():
            raise RuntimeError("verified controlled media output is missing")
        return StagedMediaArtifact(output, output.stat().st_size, sha256_file(output), probe)

    def execute_compat(
        self,
        plan: MediaExecutionPlan,
        *,
        raw_input: str,
        output_dir: Path,
        policy: ManagedMediaExecutionPolicy,
        cancel_event: threading.Event,
    ) -> tuple[StagedMediaArtifact, ...]:
        if plan.mode != MediaExecutionMode.COMPAT_MEDIA:
            raise ValueError("managed execution requires COMPAT_MEDIA plan")
        output_dir.mkdir(parents=True, exist_ok=True)
        root = output_dir.resolve()
        result = self._yt.execute_compat(
            raw_input, output_dir=output_dir, policy=policy, cancel_event=cancel_event,
        )
        staged: list[StagedMediaArtifact] = []
        seen: set[Path] = set()
        for candidate in result.output_paths:
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if resolved in seen:
                continue
            if resolved != root and root not in resolved.parents:
                raise ValueError("yt-dlp managed output escaped the Worker output directory")
            reject_symlink(candidate, allow_missing=False)
            if not resolved.is_file():
                continue
            seen.add(resolved)
            staged.append(StagedMediaArtifact(resolved, resolved.stat().st_size, sha256_file(resolved)))
        if not staged:
            raise RuntimeError("yt-dlp managed execution produced no regular output file")
        return tuple(staged)

