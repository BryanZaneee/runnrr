"""Durable UTC-day token reservations, shared by all workers."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from runnrr.config import DAILY_TOKEN_BUDGET


class BudgetExhausted(RuntimeError):
    pass


@dataclass
class TokenBudget:
    daily_limit: int
    path: Path = Path(os.environ.get("RUNNRR_BUDGET_PATH", "data/budget.sqlite"))

    @contextmanager
    def _connection(self):
        conn = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=5)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS budget (day TEXT PRIMARY KEY, used INTEGER NOT NULL)"
            )
            yield conn
            conn.commit()
        except (OSError, sqlite3.Error) as exc:
            raise BudgetExhausted("budget tracking unavailable") from exc
        finally:
            if conn is not None:
                conn.close()

    def _today(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def reserve(self, tokens: int) -> str:
        if tokens <= 0:
            raise ValueError("reservation must be positive")
        day = self._today()
        with self._connection() as conn:
            conn.execute("INSERT INTO budget VALUES (?, 0) ON CONFLICT DO NOTHING", (day,))
            changed = conn.execute(
                "UPDATE budget SET used = used + ? WHERE day = ? AND used >= 0 AND used + ? <= ?",
                (tokens, day, tokens, self.daily_limit),
            ).rowcount
            if not changed:
                raise BudgetExhausted("daily token budget exhausted")
        return day

    def settle(self, day: str, reserved: int, actual: int) -> None:
        # Reconcile only completed calls with authoritative usage. Unknown costs
        # keep their whole reservation, including after cancellation or restart.
        with self._connection() as conn:
            conn.execute(
                "UPDATE budget SET used = MAX(0, used + ?) WHERE day = ?",
                (max(0, actual) - reserved, day),
            )

    def has_capacity(self) -> bool:
        try:
            return self.stats()["remaining"] > 0
        except BudgetExhausted:
            return False

    def record(self, tokens: int) -> None:
        if tokens <= 0:
            return
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO budget VALUES (?, ?) ON CONFLICT(day) DO UPDATE SET used = used + excluded.used",
                (self._today(), tokens),
            )

    def stats(self) -> dict:
        day = self._today()
        with self._connection() as conn:
            row = conn.execute("SELECT used FROM budget WHERE day = ?", (day,)).fetchone()
        used = row[0] if row else 0
        return {
            "date": day,
            "used": used,
            "limit": self.daily_limit,
            "remaining": max(0, self.daily_limit - used),
        }


TOKEN_BUDGET = TokenBudget(daily_limit=DAILY_TOKEN_BUDGET)


def reserve_paid_call(operation: str) -> None:
    """Reserve a reviewed per-call upper bound; five apps receive $0.50 each."""
    try:
        bounds = json.loads(os.environ.get("DEMO_REQUEST_COST_BOUNDS", "{}"))
        cost = bounds.get(operation)
        if type(cost) is not int or not 0 < cost <= 500000:
            raise ValueError("missing cost bound")
    except (ValueError, TypeError, AttributeError) as exc:
        raise BudgetExhausted("paid work paused: spending bound is not configured") from exc
    with TOKEN_BUDGET._connection() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS spending (day TEXT PRIMARY KEY, used INTEGER NOT NULL CHECK(used BETWEEN 0 AND 500000))"
        )
        day = TOKEN_BUDGET._today()
        conn.execute("INSERT INTO spending VALUES (?, 0) ON CONFLICT DO NOTHING", (day,))
        if not conn.execute(
            "UPDATE spending SET used = used + ? WHERE day = ? AND used + ? <= 500000",
            (cost, day, cost),
        ).rowcount:
            raise BudgetExhausted("daily demo spending budget exhausted")
