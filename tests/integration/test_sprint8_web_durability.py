from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

from booru_studio.common.clock import ManualClock
from booru_studio.common.ids import ClientInstanceId, CommandId, StorageTargetId
from booru_studio.core.artifact_service import ArtifactService
from booru_studio.core.job_service import JobService
from booru_studio.core.media_service import MediaService
from booru_studio.domain.commands import CommandIdentity, CreateJobCommand
from booru_studio.domain.enums import DiscoveryCompleteness, InputKind, JobKind
from booru_studio.persistence.db_actor import DbActor
from booru_studio.worker.web_pipeline import WebResolverPipeline


def test_static_web_collection_persists_without_signed_candidate_urls(tmp_path: Path) -> None:
    root = tmp_path / "site"; root.mkdir()
    secret = "WEB_SIGNED_SECRET_MUST_NOT_PERSIST"
    (root / "index.html").write_text(
        f"<html><title>Web set</title><img src='/a.jpg?token={secret}'><video src='/b.mp4?sig={secret}'></video></html>",
        encoding="utf-8",
    )
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()

    clock = ManualClock(30_000, 0)
    actor = DbActor(tmp_path / "state" / "web.sqlite3", now_utc_ms=clock.utc_ms()); actor.start()
    jobs = JobService(actor, clock)
    artifacts = ArtifactService(actor, clock)
    target = StorageTargetId.new()
    artifacts.register_storage_target(storage_target_id=target, generation=1, root=tmp_path / "downloads")
    created = jobs.create_job(CreateJobCommand(
        identity=CommandIdentity(ClientInstanceId.new(), CommandId.new()),
        input_kind=InputKind.URL,
        redacted_input="http://127.0.0.1/redacted",
        job_kind=JobKind.UNKNOWN,
        title="Static web",
        storage_target_id=target,
        storage_target_generation=1,
    ))
    try:
        result = WebResolverPipeline(allow_private_root=True).resolve(
            f"http://127.0.0.1:{server.server_port}/index.html",
            cancel_event=threading.Event(), allow_browser_fallback=False,
        )
        assert result.presentation is not None and result.collection_identity is not None
        commit = MediaService(actor, clock).commit_discovery(
            job_id=created.job_id,
            presentation=result.presentation,
            batches=(result.items,),
            completeness=DiscoveryCompleteness.COMPLETE,
            collection_identity=result.collection_identity,
            collection_title=result.page_title,
        )
        assert commit.job_kind is JobKind.COLLECTION_MEDIA
        assert commit.collection_id is not None
        row = actor.submit(lambda c: c.execute(
            "SELECT kind,source_key FROM collections WHERE collection_id=?", (str(commit.collection_id),)
        ).fetchone()).result(2)
        assert row[0] == "WEB_PAGE"
        assert str(row[1]).startswith("webpage:") and "://" not in str(row[1])
        dump = "\n".join(actor.submit(lambda c: list(c.iterdump())).result(2))
        assert secret not in dump
        assert "?token=" not in dump and "?sig=" not in dump
        assert actor.submit(lambda c: c.execute("PRAGMA integrity_check").fetchone()[0]).result(2) == "ok"
    finally:
        actor.close(); server.shutdown(); server.server_close(); thread.join(timeout=2)
