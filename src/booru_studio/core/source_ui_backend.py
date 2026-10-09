from __future__ import annotations

"""Development-only in-process transport harness for the Sprint-5 QML UI.

The packaged V10 architecture remains UI process -> QLocal IPC -> Core process.  This source
harness intentionally keeps both sides in one Python process for environments where the later
Windows process host is not available, but it still sends every UI request through the real
UI-Core v1 envelope protocol and :class:`CoreUiSession`.  The UI therefore does not gain a hidden
direct JobService/SQLite path that could diverge from production semantics.
"""

import queue
import threading
from pathlib import Path
from typing import Callable, TypeVar

from booru_studio.common.clock import SystemClock
from booru_studio.core.job_service import JobService
from booru_studio.core.projection_service import ProjectionService
from booru_studio.core.ui_session import CoreUiSession
from booru_studio.ipc.envelopes import Envelope
from booru_studio.ipc.stream_connection import EnvelopeConnection
from booru_studio.persistence.db_actor import DbActor
from booru_studio.ui.ipc_client import UiCoreClient

T = TypeVar("T")
_MAX_SOURCE_INPUT_CHARS = 16_384


class _QueueEnvelopeConnection(EnvelopeConnection):
    """Small in-memory transport used only by the source harness.

    It preserves the request/response envelope boundary without pretending to validate QLocal
    behavior.  A finite receive timeout prevents a protocol defect from hanging the GUI forever.
    """

    def __init__(self, incoming: queue.Queue[Envelope], outgoing: queue.Queue[Envelope]) -> None:
        self._incoming = incoming
        self._outgoing = outgoing

    def send(self, envelope: Envelope) -> None:
        self._outgoing.put(envelope)

    def recv(self) -> Envelope:
        return self.recv_timeout(5.0)

    def recv_timeout(self, timeout_s: float) -> Envelope:
        try:
            return self._incoming.get(timeout=max(0.0, float(timeout_s)))
        except queue.Empty as exc:
            raise TimeoutError("source UI-Core transport timed out") from exc

    def close(self) -> None:
        return


def _connection_pair() -> tuple[_QueueEnvelopeConnection, _QueueEnvelopeConnection]:
    ui_to_core: queue.Queue[Envelope] = queue.Queue()
    core_to_ui: queue.Queue[Envelope] = queue.Queue()
    return (
        _QueueEnvelopeConnection(core_to_ui, ui_to_core),
        _QueueEnvelopeConnection(ui_to_core, core_to_ui),
    )


class SourceUiBackend:
    def __init__(self, db_path: Path, on_snapshot: Callable[[dict[str, object]], None]) -> None:
        self._clock = SystemClock()
        self._actor = DbActor(db_path, now_utc_ms=self._clock.utc_ms())
        self._actor.start()
        jobs = JobService(self._actor, self._clock)
        projection = ProjectionService(self._actor)
        self._session = CoreUiSession(jobs, projection)
        self._ui_connection, self._core_connection = _connection_pair()
        self._client = UiCoreClient(self._ui_connection)
        self._on_snapshot = on_snapshot
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._ui_connection.close()
        self._core_connection.close()
        self._actor.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("source UI backend is closed")

    def _exchange(self, operation: Callable[[], T]) -> T:
        self._ensure_open()
        server_error: list[BaseException] = []

        def serve() -> None:
            try:
                self._session.serve_one(self._core_connection)
            except BaseException as exc:  # surfaced to the caller after the exchange completes
                server_error.append(exc)

        thread = threading.Thread(target=serve, name="booru-source-ui-core", daemon=True)
        thread.start()
        try:
            result = operation()
        finally:
            thread.join(timeout=5.0)
        if thread.is_alive():
            raise TimeoutError("source UI-Core session did not terminate")
        if server_error:
            raise RuntimeError("source UI-Core session failed") from server_error[0]
        return result

    def refresh(self) -> None:
        snapshot = self._exchange(self._client.snapshot)
        self._on_snapshot(snapshot)

    def submit(self, raw_input: str) -> str:
        value = raw_input.strip()
        if not value:
            raise ValueError("input cannot be empty")
        if len(value) > _MAX_SOURCE_INPUT_CHARS:
            raise ValueError("input is too long")
        input_kind = "URL" if value.startswith(("http://", "https://")) else "AUTO"

        # Resolver/engine selection belongs to a later execution milestone.  A URL is not assumed
        # to be a direct file merely because it uses HTTP; YouTube/gallery/page URLs must remain
        # UNKNOWN until the resolver classifies them.
        result = self._exchange(
            lambda: self._client.create_job(
                input_kind=input_kind,
                redacted_input=value,
                job_kind="UNKNOWN",
                title=value[:4_096],
            )
        )
        self.refresh()
        return str(result["job_id"])

    def cancel(self, job_id: str) -> None:
        self._exchange(lambda: self._client.cancel_job(job_id))
        self.refresh()

    def pause(self, job_id: str) -> None:
        self._exchange(lambda: self._client.pause_job(job_id))
        self.refresh()

    def resume(self, job_id: str) -> None:
        self._exchange(lambda: self._client.resume_job(job_id))
        self.refresh()

    def move_queue(self, job_id: str, direction: str) -> None:
        self._exchange(lambda: self._client.move_queue_job(job_id, direction))
        self.refresh()
