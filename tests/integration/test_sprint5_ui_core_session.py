from __future__ import annotations

import queue
import threading
from pathlib import Path

from booru_studio.common.clock import SystemClock
from booru_studio.core.job_service import JobService
from booru_studio.core.projection_service import ProjectionService
from booru_studio.core.ui_session import CoreUiSession
from booru_studio.common.ids import ClientInstanceId, CommandId
from booru_studio.ipc.ui_core_protocol import UiCoreMessage, make_ui_envelope, validate_ui_envelope
from booru_studio.persistence.db_actor import DbActor
from booru_studio.ui.ipc_client import UiCoreClient


class _Endpoint:
    def __init__(self, incoming: queue.Queue, outgoing: queue.Queue) -> None:
        self._incoming = incoming
        self._outgoing = outgoing

    def send(self, envelope) -> None:
        self._outgoing.put(envelope)

    def recv(self):
        return self._incoming.get(timeout=2)

    def recv_timeout(self, timeout_s: float):
        return self._incoming.get(timeout=timeout_s)

    def close(self) -> None:
        return


def _pair():
    a_to_b: queue.Queue = queue.Queue()
    b_to_a: queue.Queue = queue.Queue()
    return _Endpoint(b_to_a, a_to_b), _Endpoint(a_to_b, b_to_a)


def _serve(session: CoreUiSession, endpoint: _Endpoint, count: int) -> threading.Thread:
    def run() -> None:
        for _ in range(count):
            session.serve_one(endpoint)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def test_ui_core_protocol_create_snapshot_cancel_roundtrip(tmp_path: Path) -> None:
    clock = SystemClock()
    actor = DbActor(tmp_path / "state.sqlite3", now_utc_ms=clock.utc_ms()); actor.start()
    jobs = JobService(actor, clock)
    projection = ProjectionService(actor)
    ui_ep, core_ep = _pair()
    server = _serve(CoreUiSession(jobs, projection), core_ep, 5)
    client = UiCoreClient(ui_ep)
    try:
        created = client.create_job(
            input_kind="URL",
            redacted_input="https://example.test/file.jpg",
            job_kind="DIRECT_FILE",
            title="file.jpg",
        )
        first = client.snapshot()
        assert first["queue"][0]["job_id"] == created["job_id"]
        cancelled = client.cancel_job(str(created["job_id"]))
        assert cancelled["job_id"] == created["job_id"]
        second = client.snapshot()
        assert second["downloads"][0]["control_intent"] == "CANCEL_REQUESTED"
        # An extra snapshot proves the session remains usable after a mutation.
        third = client.snapshot()
        assert third["projection_revision"] == second["projection_revision"]
    finally:
        server.join(2)
        actor.close()
    assert not server.is_alive()


def test_ui_core_rejects_malformed_payload_without_echoing_untrusted_value(tmp_path: Path) -> None:
    clock = SystemClock()
    actor = DbActor(tmp_path / "state.sqlite3", now_utc_ms=clock.utc_ms()); actor.start()
    jobs = JobService(actor, clock)
    projection = ProjectionService(actor)
    ui_ep, core_ep = _pair()
    server = _serve(CoreUiSession(jobs, projection), core_ep, 1)
    secret_marker = "TOP_SECRET_SHOULD_NOT_ECHO"
    try:
        ui_ep.send(make_ui_envelope(
            UiCoreMessage.CREATE_JOB,
            message_id="bad-1",
            payload={
                "client_instance_id": str(ClientInstanceId.new()),
                "command_id": str(CommandId.new()),
                "input_kind": "URL",
                "redacted_input": "https://example.test/file.jpg",
                "job_kind": secret_marker,
                "title": "file.jpg",
                "priority": 0,
            },
        ))
        reply = ui_ep.recv()
        assert validate_ui_envelope(reply) is UiCoreMessage.ERROR
        assert reply.payload["code"] == "INVALID_REQUEST"
        assert secret_marker not in str(reply.payload)
    finally:
        server.join(2)
        actor.close()
    assert not server.is_alive()


def test_ui_core_product_controls_roundtrip(tmp_path: Path) -> None:
    clock = SystemClock()
    actor = DbActor(tmp_path / "state.sqlite3", now_utc_ms=clock.utc_ms()); actor.start()
    jobs = JobService(actor, clock)
    projection = ProjectionService(actor)
    ui_ep, core_ep = _pair()
    server = _serve(CoreUiSession(jobs, projection), core_ep, 10)
    client = UiCoreClient(ui_ep)
    try:
        a = client.create_job(input_kind="URL", redacted_input="https://example.test/a", job_kind="UNKNOWN", title="a")
        b = client.create_job(input_kind="URL", redacted_input="https://example.test/b", job_kind="UNKNOWN", title="b")
        c = client.create_job(input_kind="URL", redacted_input="https://example.test/c", job_kind="UNKNOWN", title="c")
        first = client.snapshot()
        assert [row["job_id"] for row in first["queue"]] == [a["job_id"], b["job_id"], c["job_id"]]
        client.move_queue_job(c["job_id"], "UP")
        client.pause_job(c["job_id"])
        paused = client.snapshot()
        paused_row = next(row for row in paused["downloads"] if row["job_id"] == c["job_id"])
        assert paused_row["lifecycle"] == "PAUSED"
        assert c["job_id"] not in [row["job_id"] for row in paused["queue"]]
        client.resume_job(c["job_id"])
        resumed = client.snapshot()
        assert [row["job_id"] for row in resumed["queue"]] == [a["job_id"], b["job_id"], c["job_id"]]
        final = client.snapshot()
        assert final["projection_revision"] == resumed["projection_revision"]
    finally:
        server.join(2)
        actor.close()
    assert not server.is_alive()
