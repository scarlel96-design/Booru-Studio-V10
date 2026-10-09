from __future__ import annotations

from pathlib import Path

from booru_studio.common.clock import ManualClock
from booru_studio.persistence.db_actor import DbActor
from booru_studio.scheduler.rate_limit import DurableRateLimitRegistry
from booru_studio.scheduler.retry_state import DurableRetryBudget


def test_rate_limit_gate_survives_core_service_restart(tmp_path: Path) -> None:
    db = tmp_path / "상태" / "network.sqlite3"
    clock = ManualClock(10_000, 0)
    actor = DbActor(db, now_utc_ms=clock.utc_ms()); actor.start()
    try:
        gates = DurableRateLimitRegistry(actor, clock)
        deadline = gates.penalize("cdn.example", retry_after_s=30)
        assert deadline == 40_000
        assert gates.remaining_ms("cdn.example") == 30_000
    finally:
        actor.close()

    clock.advance(5_000)
    actor2 = DbActor(db, now_utc_ms=clock.utc_ms()); actor2.start()
    try:
        gates2 = DurableRateLimitRegistry(actor2, clock)
        assert gates2.remaining_ms("cdn.example") == 25_000
        clock.advance(25_000)
        assert gates2.clear_if_expired("cdn.example") is True
        assert gates2.remaining_ms("cdn.example") == 0
    finally:
        actor2.close()


def test_retry_hard_ceiling_survives_service_recreation(tmp_path: Path) -> None:
    db = tmp_path / "상태" / "retry.sqlite3"
    clock = ManualClock(1_000, 0)
    actor = DbActor(db, now_utc_ms=clock.utc_ms()); actor.start()
    try:
        budget = DurableRetryBudget(actor, clock)
        d1 = budget.record_failure(
            scope_kind="ITEM", scope_id="item-1", error_code="NETWORK_RESET", hard_ceiling=2
        )
        assert d1.failure_count == 1 and d1.retry_allowed
        # Recreate the application service; state authority remains SQLite.
        budget = DurableRetryBudget(actor, clock)
        d2 = budget.record_failure(
            scope_kind="ITEM", scope_id="item-1", error_code="NETWORK_RESET", hard_ceiling=2
        )
        assert d2.retry_episode_id == d1.retry_episode_id
        assert d2.failure_count == 2 and d2.retry_allowed
        d3 = budget.record_failure(
            scope_kind="ITEM", scope_id="item-1", error_code="NETWORK_RESET", hard_ceiling=2
        )
        assert d3.failure_count == 3 and not d3.retry_allowed
        row = actor.submit(lambda c: c.execute(
            "SELECT attempt_count,state FROM retry_episodes WHERE retry_episode_id=?",
            (str(d1.retry_episode_id),),
        ).fetchone()).result(2)
        assert tuple(row) == (3, "EXHAUSTED")
    finally:
        actor.close()
