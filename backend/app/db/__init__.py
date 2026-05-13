"""Postgres connection pool + low-level helpers.

We connect directly to Supabase Postgres via the transaction pooler URL
the user pastes into SUPABASE_URL. asyncpg + statement_cache_size=0 is
required for the transaction pooler (port 6543) because each transaction
gets a different backend connection, so server-side prepared statements
can't be reused.

Schema is bootstrapped on startup (see schema.bootstrap_schema). Per-entity
operations live in sibling modules:

    db.feed_cache.*   — niche feed caching
    db.assets.*       — asset CRUD
    db.chat.*         — chat message history
    db.drafts.*       — draft CRUD
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import asyncpg

from app.config import settings

log = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


def is_configured() -> bool:
    return bool(settings.supabase_url)


async def get_pool() -> asyncpg.Pool:
    """Lazy singleton. Safe to call concurrently — asyncpg.create_pool is
    idempotent under our double-check pattern because the first await yields.
    """
    global _pool
    if _pool is not None:
        return _pool
    if not settings.supabase_url:
        raise RuntimeError(
            "SUPABASE_URL is not set. Paste your Supabase Postgres "
            "transaction-pooler URL (port 6543) into .env."
        )
    log.info("Creating Postgres pool")
    _pool = await asyncpg.create_pool(
        dsn=settings.supabase_url,
        min_size=1,
        max_size=10,
        statement_cache_size=0,         # required for the transaction pooler
        command_timeout=30,
    )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def fetch_one(query: str, *args) -> Optional[asyncpg.Record]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetch_all(query: str, *args) -> list[asyncpg.Record]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(query, *args))


async def execute(query: str, *args) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)


async def execute_many(query: str, args_list: list) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(query, args_list)


def row_to_dict(row: Optional[asyncpg.Record]) -> Optional[dict[str, Any]]:
    return dict(row) if row else None


def rows_to_dicts(rows: list[asyncpg.Record]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
