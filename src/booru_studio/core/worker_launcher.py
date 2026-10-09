from __future__ import annotations

import os
import secrets
import subprocess
import sys
from dataclasses import dataclass

from booru_studio.common.clock import Clock
from booru_studio.common.ids import CoreInstanceId, EnginePackId, JobId, JobRunId, WorkerSessionId
from booru_studio.ipc.stream_connection import StreamEnvelopeConnection
from booru_studio.persistence.db_actor import DbActor
from booru_studio.persistence.repositories.worker_repository import insert_worker_session
from booru_studio.persistence.transactions.base import write_transaction
from booru_studio.worker.bootstrap import WorkerBootstrap, encode_bootstrap


@dataclass(slots=True)
class SourceWorkerProcess:
    process: subprocess.Popen[bytes]
    packet: WorkerBootstrap
    connection: StreamEnvelopeConnection


class WorkerLauncher:
    def __init__(self, db_actor: DbActor, clock: Clock, *, core_instance_id: CoreInstanceId | None = None) -> None:
        self._db = db_actor; self._clock = clock; self._core_id = core_instance_id or CoreInstanceId.new()

    @staticmethod
    def new_endpoint_name() -> str:
        return "booru-v10-worker-" + secrets.token_hex(24)

    def spawn_source_stdio(
        self, *, run_id: JobRunId, job_id: JobId, engine_pack_id: EnginePackId,
        worker_generation: int = 0,
    ) -> SourceWorkerProcess:
        read_fd, write_fd = os.pipe()
        try:
            argv = [
                sys.executable, "-m", "booru_studio.worker.main",
                "--worker-bootstrap-fd", str(read_fd), "--source-stdio-harness",
            ]
            env = os.environ.copy()
            src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            existing = env.get("PYTHONPATH")
            env["PYTHONPATH"] = src if not existing else src + os.pathsep + existing
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=(read_fd,) if os.name != "nt" else (),
                close_fds=True,
                env=env,
            )
            packet = WorkerBootstrap(
                core_instance_id=self._core_id,
                worker_session_id=WorkerSessionId.new(),
                run_id=run_id,
                job_id=job_id,
                engine_pack_id=engine_pack_id,
                worker_generation=worker_generation,
                expected_pid=process.pid,
                endpoint_name=self.new_endpoint_name(),
                secret=os.urandom(32),
                core_capabilities=("worker-tx-v1", "cancel-v1", "file-commit-v1", "direct-http-v1", "core-lease-v1"),
                worker_capabilities=("source-harness", "worker-tx-v1", "file-commit-v1", "direct-http-v1", "core-lease-v1"),
            )
            os.write(write_fd, encode_bootstrap(packet))
        finally:
            os.close(write_fd)
            os.close(read_fd)
        now = self._clock.utc_ms()
        self._db.submit(lambda c: self._insert_session(c, packet, now)).result(timeout=5)
        assert process.stdout is not None and process.stdin is not None
        connection = StreamEnvelopeConnection(process.stdout, process.stdin)
        return SourceWorkerProcess(process, packet, connection)

    @staticmethod
    def _insert_session(connection, packet: WorkerBootstrap, now: int) -> None:
        with write_transaction(connection):
            insert_worker_session(
                connection,
                worker_session_id=packet.worker_session_id,
                core_instance_id=packet.core_instance_id,
                run_id=packet.run_id,
                job_id=packet.job_id,
                engine_pack_id=packet.engine_pack_id,
                worker_generation=packet.worker_generation,
                expected_pid=packet.expected_pid,
                endpoint_name=packet.endpoint_name,
                now_utc_ms=now,
            )

    def spawn_windows_qlocal(
        self, *, executable: str, run_id: JobRunId, job_id: JobId, engine_pack_id: EnginePackId,
        worker_generation: int = 0,
    ):
        """Production-target Windows spawn path.

        This source implementation creates a random single-use QLocal endpoint, inherits only
        the bootstrap read HANDLE through STARTUPINFOEX/handle_list, and launches an absolute
        executable path. It is intentionally not executed by the Linux Sprint 3 suite.
        """
        if os.name != "nt":
            raise OSError("Windows QLocal production spawn is only available on Windows")
        from pathlib import Path as _Path
        from booru_studio.ipc.qlocal import create_user_only_server
        exe = _Path(executable).resolve(strict=True)
        endpoint = self.new_endpoint_name()
        server = create_user_only_server(endpoint)
        read_fd, write_fd = os.pipe()
        try:
            read_handle = __import__('msvcrt').get_osfhandle(read_fd)
            os.set_handle_inheritable(read_handle, True)
            startupinfo = self.windows_startupinfo_for_handle(read_handle)
            try:
                process = subprocess.Popen(
                    [str(exe), "--worker-bootstrap-handle", str(read_handle)],
                    close_fds=True, startupinfo=startupinfo,
                )
            finally:
                # Minimize the inheritable window in a multi-threaded Core process.
                os.set_handle_inheritable(read_handle, False)
            packet = WorkerBootstrap(
                core_instance_id=self._core_id, worker_session_id=WorkerSessionId.new(),
                run_id=run_id, job_id=job_id, engine_pack_id=engine_pack_id,
                worker_generation=worker_generation, expected_pid=process.pid,
                endpoint_name=endpoint, secret=os.urandom(32),
                core_capabilities=("worker-tx-v1","cancel-v1","file-commit-v1","direct-http-v1","core-lease-v1"),
                worker_capabilities=("qlocal-v1","worker-tx-v1","file-commit-v1","direct-http-v1","core-lease-v1"),
            )
            os.write(write_fd, encode_bootstrap(packet))
        finally:
            os.close(write_fd); os.close(read_fd)
        now = self._clock.utc_ms()
        self._db.submit(lambda c: self._insert_session(c, packet, now)).result(timeout=5)
        return process, packet, server

    def windows_startupinfo_for_handle(self, bootstrap_read_handle: int):
        """Build the Windows STARTUPINFOEX handle allow-list used by production launch.

        Kept import-safe on non-Windows hosts. The later Windows gate must prove the HANDLE
        inheritance and Frozen executable path end-to-end.
        """
        if os.name != "nt":
            raise OSError("Windows STARTUPINFOEX is only available on Windows")
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.lpAttributeList = {"handle_list": [bootstrap_read_handle]}
        return startupinfo
