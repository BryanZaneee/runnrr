"""Asyncpg connection pool — optional; app boots without SUPABASE_DB_URL."""
from __future__ import annotations

from typing import Any

import asyncpg

from backend import config

# ponytail: pool is process-global; fine for single-worker (the deploy is workers=1).
_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    url = config.SUPABASE_DB_URL
    if not url:
        return
    _pool = await asyncpg.create_pool(url)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def is_configured() -> bool:
    return _pool is not None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("database not configured")
    return _pool

async def fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    async with pool().acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args: Any) -> asyncpg.Record | None:
    async with pool().acquire() as conn:
        return await conn.fetchrow(query, *args)


async def execute(query: str, *args: Any) -> str:
    async with pool().acquire() as conn:
        return await conn.execute(query, *args)
