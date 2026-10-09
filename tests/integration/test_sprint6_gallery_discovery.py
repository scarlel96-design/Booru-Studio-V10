from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from booru_studio.common.clock import ManualClock
from booru_studio.common.ids import ClientInstanceId, CommandId, StorageTargetId
from booru_studio.core.artifact_service import ArtifactService
from booru_studio.core.discovery_service import DiscoveryService
from booru_studio.core.job_service import JobService
from booru_studio.domain.commands import CommandIdentity, CreateJobCommand
from booru_studio.domain.enums import DiscoveryCompleteness, InputKind, JobKind
from booru_studio.engine.adapters.gallery_dl.adapter import (
    GalleryDlAdapter, GalleryDlRecord, GalleryDirectHandoffPlanner,
)
from booru_studio.engine.contracts import HandoffSafety
from booru_studio.persistence.db_actor import DbActor
from booru_studio.worker.execution_plane import DirectHttpExecutionPlane
from booru_studio.worker.staging import perform_commit


BODY = b"gallery-sprint-6" * 4096


class State:
    referer = ""
    path = ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A003
        return

    def do_GET(self):  # noqa: N802
        State.referer = self.headers.get("Referer", "")
        State.path = self.path
        self.send_response(200)
        self.send_header("Content-Length", str(len(BODY)))
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("ETag", '"s6"')
        self.end_headers()
        self.wfile.write(BODY)


class FakeBackend:
    def __init__(self, records): self.records = tuple(records)
    def collect(self, raw_input: str): return self.records


def test_gallery_discovery_persists_only_normalized_state_then_direct_handoff(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    secret = "signed-secret-should-never-enter-db"
    cookie_secret = "cookie-secret-should-never-enter-db"
    base = f"http://127.0.0.1:{server.server_port}"
    signed_url = f"{base}/image.jpg?token={secret}"
    source_page = f"{base}/post/42"

    clock = ManualClock(1_000, 0)
    actor = DbActor(tmp_path / "상태" / "gallery.sqlite3", now_utc_ms=clock.utc_ms()); actor.start()
    jobs = JobService(actor, clock)
    artifacts = ArtifactService(actor, clock)
    discovery = DiscoveryService(actor, clock)
    target = StorageTargetId.new()
    root = tmp_path / "다운로드"
    artifacts.register_storage_target(storage_target_id=target, generation=1, root=root)
    created = jobs.create_job(CreateJobCommand(
        identity=CommandIdentity(ClientInstanceId.new(), CommandId.new()),
        input_kind=InputKind.URL,
        redacted_input=f"{base}/gallery",
        job_kind=JobKind.BOORU_GALLERY,
        title="Gallery Sprint 6",
        storage_target_id=target,
        storage_target_generation=1,
    ))

    adapter = GalleryDlAdapter(FakeBackend((
        GalleryDlRecord(3, signed_url, {
            "category": "example", "subcategory": "post", "id": 42,
            "title": "Example 42", "filename": "example_42", "extension": "jpg",
            "filesize": len(BODY), "_http_headers": {"Referer": source_page},
        }),
        GalleryDlRecord(3, f"{base}/private.jpg", {
            "category": "private", "id": 43, "filename": "private", "extension": "jpg",
            "_http_headers": {"Cookie": f"session={cookie_secret}"},
        }),
        GalleryDlRecord(6, f"{base}/child?token=child-secret", {}),
    )))

    try:
        discovered = adapter.discover(f"{base}/gallery")
        assert len(discovered.items) == 2
        safe_candidate = discovered.items[0].candidate_artifacts[0]
        unsafe_candidate = discovered.items[1].candidate_artifacts[0]
        assert safe_candidate.descriptor.handoff_safety is HandoffSafety.CONDITIONAL
        assert unsafe_candidate.descriptor.handoff_safety is HandoffSafety.UNSAFE

        cycle = discovery.begin(created.job_id)
        persisted = discovery.ingest_batch(
            job_id=created.job_id, cycle_id=cycle, batch_sequence=0,
            descriptors=list(discovered.items),
        )
        discovery.seal(cycle, completeness=DiscoveryCompleteness.COMPLETE)
        assert len(discovery.list_items(created.job_id)) == 2
        assert len(persisted) == 2

        first = persisted[0]
        plan = artifacts.plan_artifact(
            job_id=created.job_id, item_id=first.item_id,
            storage_target_id=target, storage_generation=1,
            relative_path=safe_candidate.suggested_filename,
            expected_size=len(BODY),
        )
        wire = GalleryDirectHandoffPlanner.build(
            safe_candidate, artifact_id=str(plan.artifact_id), generation=1,
            staging_path=plan.staging_path,
        )
        staged: list[dict[str, object]] = []
        outcome = DirectHttpExecutionPlane().run(
            {"mode": "DIRECT_HTTP", "parallelism": 1, "transfers": [wire]},
            cancel_event=threading.Event(), on_staged=staged.append,
        )
        assert outcome.transfer_count == 1 and len(staged) == 1
        state = artifacts.register_resume_sidecar(Path(str(staged[0]["sidecar_path"])))
        grant = artifacts.prepare_commit(artifact_id=state.artifact_id)
        final = artifacts.finalize_commit(perform_commit(grant))
        assert final.committed_state_revision > 0
        assert plan.final_path.read_bytes() == BODY
        assert State.referer == source_page
        assert secret in State.path  # ephemeral signed URL reached the transfer engine

        link = actor.submit(lambda c: c.execute(
            "SELECT item_id,lifecycle FROM artifacts WHERE artifact_id=?", (str(plan.artifact_id),)
        ).fetchone()).result(2)
        assert str(link["item_id"]) == str(first.item_id)
        assert str(link["lifecycle"]) == "COMMITTED"

        # Scan every durable SQL value through iterdump: signed URLs, cookie values and queued child
        # URLs are runtime-only and must not become ordinary durable state.
        dump = "\n".join(actor.submit(lambda c: list(c.iterdump())).result(2))
        assert secret not in dump
        assert cookie_secret not in dump
        assert "child-secret" not in dump
        assert "PRAGMA integrity_check" not in dump
        assert actor.submit(lambda c: c.execute("PRAGMA integrity_check").fetchone()[0]).result(2) == "ok"
    finally:
        actor.close(); server.shutdown(); server.server_close(); thread.join(2)


def test_job_classification_is_one_way_and_artifact_cannot_cross_job_item(tmp_path: Path) -> None:
    clock = ManualClock(10_000, 0)
    actor = DbActor(tmp_path / "classify.sqlite3", now_utc_ms=clock.utc_ms()); actor.start()
    jobs = JobService(actor, clock)
    discovery = DiscoveryService(actor, clock)
    artifacts = ArtifactService(actor, clock)
    target = StorageTargetId.new(); artifacts.register_storage_target(storage_target_id=target, generation=1, root=tmp_path / "out")
    def make(title: str):
        return jobs.create_job(CreateJobCommand(
            identity=CommandIdentity(ClientInstanceId.new(), CommandId.new()), input_kind=InputKind.URL,
            redacted_input="https://example.test/", job_kind=JobKind.UNKNOWN, title=title,
            storage_target_id=target, storage_target_generation=1,
        ))
    first = make("first"); second = make("second")
    try:
        revision = jobs.classify_job(first.job_id, JobKind.BOORU_GALLERY)
        assert revision > 0
        assert jobs.get_job(first.job_id).kind is JobKind.BOORU_GALLERY
        with __import__("pytest").raises(RuntimeError):
            jobs.classify_job(first.job_id, JobKind.DIRECT_FILE)

        desc = GalleryDlAdapter(FakeBackend((GalleryDlRecord(3, "https://cdn.test/x.jpg", {
            "category": "x", "id": 1, "filename": "x", "extension": "jpg",
        }),))).discover("https://example.test/").items[0]
        cycle = discovery.begin(first.job_id)
        pair = discovery.ingest_batch(job_id=first.job_id, cycle_id=cycle, batch_sequence=0, descriptors=[desc])[0]
        with __import__("pytest").raises(ValueError, match="different Job"):
            artifacts.plan_artifact(
                job_id=second.job_id, item_id=pair.item_id, storage_target_id=target,
                storage_generation=1, relative_path="cross.jpg",
            )
    finally:
        actor.close()
