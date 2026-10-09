from __future__ import annotations

import pytest

from booru_studio.common.clock import ManualClock


def test_manual_clock_separates_wall_and_monotonic_time() -> None:
    clock = ManualClock(_utc_ms=1_000, _monotonic_ms=200)
    clock.set_utc_ms(100)
    assert clock.utc_ms() == 100
    assert clock.monotonic_ms() == 200
    clock.advance(50)
    assert clock.utc_ms() == 150
    assert clock.monotonic_ms() == 250


def test_manual_clock_rejects_negative_monotonic_advance() -> None:
    with pytest.raises(ValueError):
        ManualClock().advance(-1)
