"""Daily token budget tracker.

A single module-level `TOKEN_BUDGET` is configured from `DAILY_TOKEN_BUDGET` at
import time. The chat handler refuses requests when `has_capacity()` is false
and records actual usage at the end of each turn. The counter resets on the
first call after the local server date changes.

Process-local; if you scale beyond one worker, replace the backing store with
Redis or similar. Single-process is fine for the portfolio deploy.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date

from runnrr.config import DAILY_TOKEN_BUDGET


@dataclass
class TokenBudget:
    daily_limit: int
    _date: date = field(default_factory=date.today)
    _used: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _maybe_reset_locked(self) -> None:
        today = date.today()
        if today != self._date:
            self._date = today
            self._used = 0

    def has_capacity(self) -> bool:
        with self._lock:
            self._maybe_reset_locked()
            return self._used < self.daily_limit

    def record(self, tokens: int) -> None:
        if tokens <= 0:
            return
        with self._lock:
            self._maybe_reset_locked()
            self._used += tokens

    def reset(self) -> None:
        with self._lock:
            self._date = date.today()
            self._used = 0

    def stats(self) -> dict:
        with self._lock:
            self._maybe_reset_locked()
            return {
                "date": self._date.isoformat(),
                "used": self._used,
                "limit": self.daily_limit,
                "remaining": max(0, self.daily_limit - self._used),
            }


TOKEN_BUDGET = TokenBudget(daily_limit=DAILY_TOKEN_BUDGET)
