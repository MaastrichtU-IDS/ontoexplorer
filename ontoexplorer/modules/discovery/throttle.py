"""Peer-politeness throttling for MOD-API discovery.

``PeerRateLimiter`` spaces successive requests to a peer at least
``min_interval_ms`` apart; ``RunBudget`` caps how many candidates one harvest
run may admit. Clock and sleep are injectable so tests are deterministic.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class PeerRateLimiter:
    """Enforce a minimum interval between successive ``wait()`` calls.

    ``min_interval_ms <= 0`` disables throttling. The first ``wait()`` never
    blocks. Not safe for concurrent callers on one instance beyond what a
    single sequential harvest loop needs (use one limiter per peer).
    """

    def __init__(
        self,
        min_interval_ms: int,
        *,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = max(0, min_interval_ms) / 1000.0
        self._now = now
        self._sleep = sleep
        self._last: float | None = None

    async def wait(self) -> None:
        if self._interval <= 0:
            return
        if self._last is not None:
            remaining = self._interval - (self._now() - self._last)
            if remaining > 0:
                await self._sleep(remaining)
        self._last = self._now()


class RunBudget:
    """Per-run cap on the number of candidates admitted."""

    def __init__(self, max_candidates: int) -> None:
        self._remaining = max(0, max_candidates)

    @property
    def remaining(self) -> int:
        return self._remaining

    def take(self) -> bool:
        if self._remaining <= 0:
            return False
        self._remaining -= 1
        return True
