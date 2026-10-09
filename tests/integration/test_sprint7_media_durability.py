from __future__ import annotations

from pathlib import Path

import pytest

from booru_studio.common.clock import ManualClock
from booru_studio.common.ids import ClientInstanceId, CommandId, StorageTargetId
from booru_studio.core.artifact_service import ArtifactService
from booru_studio.core.job_service import JobService
from booru_studio.core.media_service import MediaService
from booru_studio.domain.commands import CommandIdentity, CreateJobCommand
from booru_studio.domain.enums import DiscoveryCompleteness, InputKind, JobKind
from booru_studio.engine.adapters.yt_dlp import YtDlpAdapter
from booru_studio.persistence.db_actor import DbActor


class FakeBackend:
    def __init__(self, payload):
        self.payload = payload

    def probe_extractor(self, raw_input: str):
        return ("Youtube", False)

    def extract(self, raw_input: str, *, flat_playlist: bool):
        return self.payload

    def download(self, *args, **kwargs):
        raise AssertionError("not used")


def _setup(tmp_path: Path):
    clock = ManualClock(10_000, 0)
    actor = DbActor(tmp_path / "상태" / "media.sqlite3", now_utc_ms=clock.utc_ms())
    actor.start()
    jobs = JobService(actor, clock)
    artifacts = ArtifactService(actor, clock)
    target = StorageTargetId.new()
    artifacts.register_storage_target(
        storage_target_id=target, generation=1, root=tmp_path / "다운로드" / "영상"
    )
    return clock, actor, jobs, target


def _job(jobs: JobService, target: StorageTargetId, title: str):
    return jobs.create_job(CreateJobCommand(
        identity=CommandIdentity(ClientInstanceId.new(), CommandId.new()),
        input_kind=InputKind.URL,
        redacted_input="https://www.youtube.com/redacted",
        job_kind=JobKind.UNKNOWN,
        title=title,
        storage_target_id=target,
        storage_target_generation=1,
    ))


def test_playlist_presentation_and_memberships_are_durable_without_engine_secrets(tmp_path: Path) -> None:
    clock, actor, jobs, target = _setup(tmp_path)
    secret = "SIGNED_MEDIA_SECRET_MUST_NOT_PERSIST"
    cookie = "COOKIE_SECRET_MUST_NOT_PERSIST"
    payload = {
        "_type": "playlist",
        "id": "PL-safe-1",
        "extractor_key": "YoutubeTab",
        "title": "Playlist title",
        "entries": [
            {
                "id": "v1", "extractor_key": "Youtube", "title": "One",
                "formats": [{"url": f"https://cdn.test/one.mp4?token={secret}", "http_headers": {"Cookie": cookie}}],
            },
            {"id": "v2", "extractor_key": "Youtube", "title": "Two"},
        ],
    }
    created = _job(jobs, target, "Playlist")
    result = YtDlpAdapter(FakeBackend(payload)).discover(
        f"https://www.youtube.com/playlist?list=PL-safe-1&token={secret}"
    )
    media = MediaService(actor, clock)
    try:
        committed = media.commit_discovery(
            job_id=created.job_id,
            presentation=result.presentation,
            batches=(result.items,),
            completeness=DiscoveryCompleteness.PARTIAL,
            collection_identity=result.collection_identity,
            collection_title=result.collection_title,
        )
        assert committed.job_kind is JobKind.COLLECTION_MEDIA
        assert jobs.get_job(created.job_id).kind is JobKind.COLLECTION_MEDIA
        assert committed.collection_id is not None
        assert len(committed.items) == 2
        row = actor.submit(lambda c: c.execute(
            "SELECT kind,title,source_key FROM collections WHERE collection_id=?",
            (str(committed.collection_id),),
        ).fetchone()).result(2)
        assert tuple(row) == ("PLAYLIST", "Playlist title", "collection:youtubetab:PL-safe-1")
        memberships = actor.submit(lambda c: c.execute(
            "SELECT COUNT(*) FROM collection_memberships WHERE collection_id=?",
            (str(committed.collection_id),),
        ).fetchone()[0]).result(2)
        assert memberships == 2

        dump = "\n".join(actor.submit(lambda c: list(c.iterdump())).result(2))
        assert secret not in dump
        assert cookie not in dump
        assert "cdn.test/one.mp4" not in dump
        assert actor.submit(lambda c: c.execute("PRAGMA integrity_check").fetchone()[0]).result(2) == "ok"
    finally:
        actor.close()


def test_single_media_is_classified_individual_and_does_not_create_collection(tmp_path: Path) -> None:
    clock, actor, jobs, target = _setup(tmp_path)
    created = _job(jobs, target, "Single")
    result = YtDlpAdapter(FakeBackend({
        "id": "single-1", "extractor_key": "Youtube", "title": "Standalone",
        "webpage_url": "https://www.youtube.com/watch?v=single-1",
    })).discover("https://www.youtube.com/watch?v=single-1")
    media = MediaService(actor, clock)
    try:
        committed = media.commit_discovery(
            job_id=created.job_id,
            presentation=result.presentation,
            batches=(result.items,),
            completeness=DiscoveryCompleteness.COMPLETE,
        )
        assert committed.job_kind is JobKind.SINGLE_MEDIA
        assert committed.collection_id is None
        assert len(committed.items) == 1
        assert actor.submit(lambda c: c.execute("SELECT COUNT(*) FROM collections").fetchone()[0]).result(2) == 0
    finally:
        actor.close()


def test_individual_media_contract_rejects_multiple_items_before_durable_write(tmp_path: Path) -> None:
    clock, actor, jobs, target = _setup(tmp_path)
    created = _job(jobs, target, "Invalid")
    first = YtDlpAdapter(FakeBackend({"id": "one", "extractor_key": "X", "title": "One"})).discover("https://x.test/one")
    second = YtDlpAdapter(FakeBackend({"id": "two", "extractor_key": "X", "title": "Two"})).discover("https://x.test/two")
    media = MediaService(actor, clock)
    try:
        with pytest.raises(ValueError, match="exactly one"):
            media.commit_discovery(
                job_id=created.job_id,
                presentation=first.presentation,
                batches=((first.items[0], second.items[0]),),
                completeness=DiscoveryCompleteness.COMPLETE,
            )
        assert jobs.get_job(created.job_id).kind is JobKind.UNKNOWN
        assert actor.submit(lambda c: c.execute("SELECT COUNT(*) FROM discovery_cycles").fetchone()[0]).result(2) == 0
    finally:
        actor.close()
