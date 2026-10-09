from __future__ import annotations

import threading
import time

from booru_studio.ipc.core_worker_protocol import CoreWorkerMessage, make_envelope, validate_envelope
from booru_studio.scheduler.coordinator import ParallelTransferScheduler
from booru_studio.worker.bootstrap import WorkerBootstrap
from booru_studio.worker.main import _CoreLeaseState
from booru_studio.common.ids import CoreInstanceId, EnginePackId, JobId, JobRunId, WorkerSessionId


def _packet() -> WorkerBootstrap:
    return WorkerBootstrap(
        core_instance_id=CoreInstanceId.new(), worker_session_id=WorkerSessionId.new(),
        run_id=JobRunId.new(), job_id=JobId.new(), engine_pack_id=EnginePackId.new(),
        worker_generation=0, expected_pid=123, endpoint_name="lease-test", secret=b"x"*32,
        core_capabilities=("core-lease-v1",), worker_capabilities=("core-lease-v1",),
    )


def test_core_lease_protocol_is_control_plane_and_bounded():
    packet=_packet()
    env=make_envelope(CoreWorkerMessage.CORE_LEASE,message_id="lease-2",payload={
        "run_id":str(packet.run_id),"core_lease_epoch":2,"valid_for_ms":6000,
    })
    assert validate_envelope(env) is CoreWorkerMessage.CORE_LEASE


def test_worker_lease_expiry_closes_and_fresh_epoch_reopens_admission(monkeypatch):
    now=[100.0]
    monkeypatch.setattr("booru_studio.worker.main.time.monotonic",lambda:now[0])
    packet=_packet(); state=_CoreLeaseState({"core_lease_epoch":1,"core_lease_valid_for_ms":1000})
    assert state.operation_gate.is_set()
    now[0]=101.1; state.expire_if_needed(); assert not state.operation_gate.is_set()
    env=make_envelope(CoreWorkerMessage.CORE_LEASE,message_id="l2",payload={
        "run_id":str(packet.run_id),"core_lease_epoch":2,"valid_for_ms":1000,
    })
    state.accept_envelope(env,packet); assert state.operation_gate.is_set()


def test_scheduler_does_not_start_new_operation_while_core_lease_gate_is_closed():
    gate=threading.Event(); started=threading.Event()
    def factory():
        def worker(value,cancel_event,admission):
            started.set(); return value*2
        return worker
    scheduler=ParallelTransferScheduler(1,worker_factory=factory,operation_gate=gate)
    try:
        future=scheduler.submit(21)
        time.sleep(0.08)
        assert not started.is_set() and not future.done()
        gate.set()
        assert future.result(timeout=2)==42
    finally:
        scheduler.close()
