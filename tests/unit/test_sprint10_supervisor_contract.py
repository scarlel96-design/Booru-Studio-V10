import pytest

from booru_studio.runtime.supervisor_contract import CoreHealth, SupervisorLeasePolicy, SupervisorLeaseTracker, WorkerLeaseFence


def test_supervisor_requires_timeout_and_failed_probe_before_unresponsive():
    t=SupervisorLeaseTracker(SupervisorLeasePolicy(100,300,200)); t.heartbeat(elapsed_ms=1000,power_epoch=0)
    assert t.evaluate(elapsed_ms=1050,process_alive=True,health_probe_ok=False) is CoreHealth.HEALTHY
    assert t.evaluate(elapsed_ms=1200,process_alive=True,health_probe_ok=False) is CoreHealth.SUSPECT
    assert t.evaluate(elapsed_ms=1400,process_alive=True,health_probe_ok=True) is CoreHealth.SUSPECT
    assert t.evaluate(elapsed_ms=1400,process_alive=True,health_probe_ok=False) is CoreHealth.UNRESPONSIVE


def test_resume_fences_old_heartbeat_and_gives_grace():
    t=SupervisorLeaseTracker(SupervisorLeasePolicy(100,300,200)); t.heartbeat(elapsed_ms=1000,power_epoch=0)
    epoch=t.resume(elapsed_ms=1010); assert epoch==1
    assert t.evaluate(elapsed_ms=1100,process_alive=True,health_probe_ok=False) is CoreHealth.RESUME_GRACE
    with pytest.raises(ValueError): t.heartbeat(elapsed_ms=1110,power_epoch=0)
    t.heartbeat(elapsed_ms=1120,power_epoch=1)
    assert t.evaluate(elapsed_ms=1130,process_alive=True,health_probe_ok=False) is CoreHealth.HEALTHY


def test_worker_lease_fence_blocks_new_admission_after_power_resume():
    f=WorkerLeaseFence(); f.accept_core_lease(power_epoch=0,core_lease_epoch=1); assert f.may_admit_new_operation
    f.on_power_resume(1); assert not f.may_admit_new_operation
    with pytest.raises(ValueError): f.accept_core_lease(power_epoch=0,core_lease_epoch=2)
    f.accept_core_lease(power_epoch=1,core_lease_epoch=2); assert f.may_admit_new_operation
