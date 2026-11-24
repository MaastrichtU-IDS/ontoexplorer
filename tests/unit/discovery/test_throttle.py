"""Unit tests for the peer-politeness rate limiter and run budget."""

from __future__ import annotations

import pytest

from ontoexplorer.modules.discovery.throttle import PeerRateLimiter, RunBudget


class FakeClock:
    """Shared monotonic clock; the recording sleep advances it."""

    def __init__(self) -> None:
        self.t = 100.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


@pytest.mark.asyncio
async def test_rate_limiter_enforces_interval() -> None:
    clock = FakeClock()
    limiter = PeerRateLimiter(500, now=clock.now, sleep=clock.sleep)

    await limiter.wait()  # first call never blocks
    assert clock.slept == [] or clock.slept == [0]

    clock.slept.clear()
    await limiter.wait()  # back-to-back: full interval
    assert clock.slept == [pytest.approx(0.5)]

    clock.slept.clear()
    clock.t += 0.2  # 200ms elapsed -> 300ms remaining
    await limiter.wait()
    assert clock.slept == [pytest.approx(0.3)]

    clock.slept.clear()
    clock.t += 5.0  # well past the interval -> no sleep
    await limiter.wait()
    assert all(s == 0 for s in clock.slept)


@pytest.mark.asyncio
async def test_rate_limiter_zero_interval_never_sleeps() -> None:
    clock = FakeClock()
    limiter = PeerRateLimiter(0, now=clock.now, sleep=clock.sleep)
    for _ in range(3):
        await limiter.wait()
    assert clock.slept == []

    neg = PeerRateLimiter(-10, now=clock.now, sleep=clock.sleep)
    await neg.wait()
    await neg.wait()
    assert clock.slept == []


def test_run_budget_caps() -> None:
    budget = RunBudget(2)
    assert budget.remaining == 2
    assert budget.take() is True
    assert budget.remaining == 1
    assert budget.take() is True
    assert budget.remaining == 0
    assert budget.take() is False
    assert budget.remaining == 0


def test_run_budget_negative_never_negative() -> None:
    budget = RunBudget(-3)
    assert budget.remaining == 0
    assert budget.take() is False
    assert budget.remaining == 0
