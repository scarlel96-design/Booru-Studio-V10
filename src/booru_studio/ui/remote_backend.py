from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass

from booru_studio.common.ids import ClientInstanceId, CommandId
from booru_studio.domain.enums import InputKind, JobKind
from booru_studio.ipc.qlocal import connect_local_socket
from booru_studio.ipc.qt_connection import QtLocalEnvelopeConnection
from booru_studio.ui.ipc_client import UiCoreClient, UiCoreCommandError


@dataclass(frozen=True, slots=True)
class _Task:
    operation: str
    args: tuple[object, ...] = ()
    success_context: object | None = None
    command_id: CommandId | None = None

    @property
    def is_mutation(self) -> bool:
        return self.command_id is not None


class RemoteUiBackend:
    """Packaged UI backend with QLocal I/O isolated from the GUI thread.

    The worker thread owns the QLocalSocket for its entire lifetime. Mutating commands are never
    blindly retried after an uncertain transport failure: durable command receipts make replay
    possible only when the original command identity is preserved, so Sprint 10 instead marks the
    projection stale and requires a safe snapshot reconciliation/reconnect.
    """

    is_async = True
    _STOP = object()

    def __init__(
        self,
        endpoint: str,
        on_projection: Callable[[dict[str, object]], None],
        *,
        on_error: Callable[[str, bool, bool], None],
        on_idle: Callable[[], None],
        on_success: Callable[[str, object | None], None],
        connect_timeout_ms: int = 1500,
    ) -> None:
        if not endpoint or len(endpoint) > 240:
            raise ValueError("invalid Core endpoint")
        if connect_timeout_ms <= 0 or connect_timeout_ms > 5000:
            raise ValueError("invalid Core connection timeout")
        self._endpoint = endpoint
        self._timeout_ms = connect_timeout_ms
        self._client_instance_id = ClientInstanceId.new()
        self._on_projection = on_projection
        self._on_error = on_error
        self._on_idle = on_idle
        self._on_success = on_success
        self._tasks: queue.Queue[_Task | object] = queue.Queue(maxsize=128)
        self._closed = threading.Event()
        self._connection: QtLocalEnvelopeConnection | None = None
        self._client: UiCoreClient | None = None
        self._thread = threading.Thread(target=self._run, name="BooruStudio-UI-Core-IPC", daemon=True)
        self._thread.start()

    def _enqueue(self, task: _Task) -> None:
        if self._closed.is_set():
            raise RuntimeError("remote UI backend is closed")
        try:
            self._tasks.put_nowait(task)
        except queue.Full as exc:
            raise RuntimeError("UI-Core command queue is full") from exc

    def _connect(self) -> UiCoreClient:
        if self._client is not None:
            return self._client
        socket = connect_local_socket(self._endpoint, timeout_ms=self._timeout_ms)
        self._connection = QtLocalEnvelopeConnection(
            socket,
            timeout_ms=self._timeout_ms,
            max_frame_bytes=2 * 1024 * 1024,
        )
        self._client = UiCoreClient(self._connection, client_instance_id=self._client_instance_id)
        return self._client

    def _disconnect(self) -> None:
        connection, self._connection = self._connection, None
        self._client = None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    def _execute(self, task: _Task) -> None:
        client = self._connect()
        op = task.operation
        if op == "refresh":
            snapshot = client.snapshot()
        elif op == "submit":
            value = str(task.args[0])
            input_kind = InputKind.URL if value.lower().startswith(("http://", "https://")) else InputKind.AUTO
            client.create_job(
                input_kind=input_kind.value,
                redacted_input=value,
                job_kind=JobKind.UNKNOWN.value,
                title=value,
                command_id=task.command_id,
            )
            snapshot = client.snapshot()
        elif op == "cancel":
            client.cancel_job(str(task.args[0]), command_id=task.command_id); snapshot = client.snapshot()
        elif op == "pause":
            client.pause_job(str(task.args[0]), command_id=task.command_id); snapshot = client.snapshot()
        elif op == "resume":
            client.resume_job(str(task.args[0]), command_id=task.command_id); snapshot = client.snapshot()
        elif op == "move":
            client.move_queue_job(str(task.args[0]), str(task.args[1]), command_id=task.command_id); snapshot = client.snapshot()
        else:  # pragma: no cover - internal invariant
            raise ValueError(f"unsupported remote operation: {op}")
        self._on_projection(snapshot)
        self._on_success(op, task.success_context)

    def _run(self) -> None:
        while True:
            task = self._tasks.get()
            try:
                if task is self._STOP or self._closed.is_set():
                    self._disconnect()
                    return
                assert isinstance(task, _Task)
                try:
                    self._execute(task)
                except UiCoreCommandError as exc:
                    # A Core-level rejection is authoritative and does not imply lost transport.
                    self._on_error(str(exc), False, False)
                except Exception as first_exc:
                    # One reconnect replay is safe because mutation tasks retain both the same
                    # client_instance_id and the exact same durable command_id. Snapshot refresh is
                    # read-only and is also safe to replay. Never manufacture a fresh mutation ID.
                    self._disconnect()
                    try:
                        self._execute(task)
                    except UiCoreCommandError as exc:
                        self._on_error(str(exc), False, False)
                    except Exception as second_exc:
                        self._disconnect()
                        self._on_error(str(second_exc or first_exc), True, True)
            finally:
                if task is not self._STOP:
                    self._on_idle()
                self._tasks.task_done()

    def refresh(self) -> None:
        self._enqueue(_Task("refresh"))

    def submit(self, raw_input: str) -> None:
        value = raw_input.strip()
        if not value:
            raise ValueError("input must not be empty")
        self._enqueue(_Task("submit", (value,), success_context=raw_input, command_id=CommandId.new()))

    def cancel(self, job_id: str) -> None:
        self._enqueue(_Task("cancel", (job_id,), command_id=CommandId.new()))

    def pause(self, job_id: str) -> None:
        self._enqueue(_Task("pause", (job_id,), command_id=CommandId.new()))

    def resume(self, job_id: str) -> None:
        self._enqueue(_Task("resume", (job_id,), command_id=CommandId.new()))

    def move_queue(self, job_id: str, direction: str) -> None:
        self._enqueue(_Task("move", (job_id, direction), command_id=CommandId.new()))

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._tasks.put_nowait(self._STOP)
        except queue.Full:
            # Bounded queue backpressure is preferable to blocking the Qt shutdown path. The
            # worker is daemonized and each transport wait is itself bounded.
            return
        self._thread.join(timeout=max(2.0, self._timeout_ms / 1000 + 0.5))
        if not self._thread.is_alive():
            # Socket was created/used/closed on the same worker thread via _run final operations.
            return
