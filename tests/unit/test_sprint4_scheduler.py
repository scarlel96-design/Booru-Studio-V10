from __future__ import annotations

import threading

import pytest

from booru_studio.common.clock import ManualClock
from booru_studio.common.random_source import DeterministicRandomSource
from booru_studio.scheduler.adaptive_network import HostAdaptiveLimiter
from booru_studio.scheduler.resources import PermitState, TransferPermitPool
from booru_studio.scheduler.retry import RetryPolicy, transient_network_reason


def test_permit_pool_shrink_keeps_excess_issued_as_draining() -> None:
    pool = TransferPermitPool(4)
    leases = [pool.acquire() for _ in range(4)]
    snap = pool.resize(2)
    assert (snap.issued, snap.active, snap.draining) == (4, 2, 2)
    assert sum(lease.state is PermitState.DRAINING for lease in leases) == 2

    acquired: list[object] = []
    done = threading.Event()

    def waiter() -> None:
        acquired.append(pool.acquire(timeout_s=1.0))
        done.set()

    thread = threading.Thread(target=waiter)
    thread.start()
    # Releasing only one permit leaves issued=3 > target=2, so no new grant.
    leases[-1].release()
    assert not done.wait(0.1)
    # Releasing another reaches issued=2, still no room until issued < target.
    leases[-2].release()
    assert not done.wait(0.1)
    # Releasing one active permit creates one slot.
    leases[0].release()
    assert done.wait(0.5)
    thread.join(1)
    assert pool.snapshot().issued == 2
    acquired[0].release()  # type: ignore[attr-defined]
    leases[1].release()
    assert pool.snapshot().issued == 0


def test_permit_pool_never_exceeds_hard_capacity_under_contention() -> None:
    pool = TransferPermitPool(5)
    barrier = threading.Barrier(21)
    lock = threading.Lock()
    observed_peak = 0

    def worker() -> None:
        nonlocal observed_peak
        barrier.wait()
        with pool.acquire():
            with lock:
                observed_peak = max(observed_peak, pool.snapshot().issued)
            threading.Event().wait(0.02)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(2)
    assert observed_peak == 5
    assert pool.snapshot().peak_issued == 5


def test_host_adaptive_limiter_reduces_and_recovers_slowly() -> None:
    clock = ManualClock(1_000, 1_000)
    limiter = HostAdaptiveLimiter(10, minimum=2, clock=clock)
    assert limiter.snapshot("https://cdn.example/a").limit == 10
    assert limiter.transient_failure("https://cdn.example/a") == (10, 10, 1)
    old, new, streak = limiter.transient_failure("https://cdn.example/b")
    assert (old, new, streak) == (10, 7, 2)
    # One lucky success never restores full concurrency.
    assert limiter.success("cdn.example") == (7, 7)
    clock.advance(100_000)
    for _ in range(11):
        limiter.success("https://cdn.example/x")
    assert limiter.snapshot("cdn.example").limit == 8


def test_retry_policy_hard_ceiling_and_deterministic_jitter() -> None:
    policy = RetryPolicy(hard_ceiling=3, base_delay_s=1.0, max_delay_s=10.0, jitter_s=0.5)
    rng = DeterministicRandomSource(42)
    delays = [policy.delay_seconds(i, rng) for i in range(1, 5)]
    assert policy.can_retry(1)
    assert policy.can_retry(3)
    assert not policy.can_retry(4)
    assert 1.0 <= delays[0] <= 1.5
    assert 2.0 <= delays[1] <= 2.5
    assert 4.0 <= delays[2] <= 4.5
    assert 8.0 <= delays[3] <= 8.5


class _WrappedReset(Exception):
    pass


class _WinReset(OSError):
    winerror = 10054


def test_nested_winerror_10054_is_classified() -> None:
    inner = _WinReset("reset")
    outer = _WrappedReset("wrapper", (inner,))
    assert transient_network_reason(outer) == "WinError 10054"


def test_permit_acquire_cancellation() -> None:
    pool = TransferPermitPool(1)
    lease = pool.acquire()
    cancel = threading.Event(); cancel.set()
    with pytest.raises(InterruptedError):
        pool.acquire(cancel, timeout_s=1.0)
    lease.release()


def test_draining_state_is_not_silently_reactivated_by_unrelated_release() -> None:
    pool = TransferPermitPool(4)
    leases = [pool.acquire() for _ in range(4)]
    pool.resize(2)
    draining = [lease for lease in leases if lease.state is PermitState.DRAINING]
    active = [lease for lease in leases if lease.state is PermitState.ACTIVE]
    assert len(draining) == 2 and len(active) == 2
    active[0].release()
    # Shrink semantics are monotonic: both owners already told to drain remain draining.
    assert all(lease.state is PermitState.DRAINING for lease in draining)
    for lease in leases:
        lease.release()


def test_scheduler_worker_factory_failure_fails_closed() -> None:
    from booru_studio.scheduler.coordinator import ParallelTransferScheduler

    def factory():
        raise RuntimeError("factory boom")

    scheduler = ParallelTransferScheduler(1, worker_factory=factory)
    try:
        # The worker can fail just before or just after submit; either path must become observable.
        threading.Event().wait(0.05)
        with pytest.raises(RuntimeError):
            scheduler.submit("x")
    finally:
        scheduler.close(timeout_s=0.5)
