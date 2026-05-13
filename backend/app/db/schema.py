"""Schema bootstrap.

On backend startup we check whether the v2 tables exist and, if not, execute
backend/supabase/schema.sql against the configured database. Idempotent —
the schema file uses CREATE TABLE IF NOT EXISTS and ON CONFLICT DO UPDATE
for the seed niches.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.db import fetch_one, get_pool

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "supabase" / "schema.sql"

REQUIRED_TABLES = ("niches", "feed_cache", "assets", "chat_messages", "drafts", "artifacts")


async def bootstrap_schema() -> bool:
    """Ensure v2 tables exist + seed niches. Returns True if it ran the schema.

    Idempotent: cheap fast-path that just checks `niches.count() > 0` and
    bails. Full SQL run only on a fresh database.
    """
    try:
        row = await fetch_one(
            """
            select count(*)::int as n from information_schema.tables
            where table_schema = 'public' and table_name = any($1::text[])
            """,
            list(REQUIRED_TABLES),
        )
    except Exception as e:
        log.warning("Schema check failed (DB unreachable?): %s", e)
        return False

    have = int(row["n"]) if row else 0
    if have == len(REQUIRED_TABLES):
        log.info("Schema OK — all %d tables present", have)
        return False

    log.warning("Schema incomplete (have %d / %d tables) — running schema.sql",
                have, len(REQUIRED_TABLES))

    if not SCHEMA_PATH.is_file():
        log.error("schema.sql not found at %s", SCHEMA_PATH)
        return False

    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Run in a single transaction so a partial failure doesn't leave the
        # DB half-baked.
        async with conn.transaction():
            await conn.execute(sql)

    log.info("Schema applied successfully")
    return True
