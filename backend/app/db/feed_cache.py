"""feed_cache table: one row per niche, refreshed every ~6h."""
from __future__ import annotations

import json
from typing import Optional

from app.db import execute, fetch_one, row_to_dict


async def get(niche_slug: str) -> Optional[dict]:
    """Return {niche_slug, fetched_at, items_json} or None."""
    row = await fetch_one(
        "select niche_slug, fetched_at, items_json from feed_cache where niche_slug = $1",
        niche_slug,
    )
    d = row_to_dict(row)
    if d and isinstance(d.get("items_json"), str):
        try:
            d["items_json"] = json.loads(d["items_json"])
        except json.JSONDecodeError:
            d["items_json"] = []
    return d


async def upsert(niche_slug: str, items: list[dict]) -> None:
    await execute(
        """
        insert into feed_cache (niche_slug, items_json, fetched_at)
        values ($1, $2::jsonb, now())
        on conflict (niche_slug) do update
        set items_json = excluded.items_json,
            fetched_at = excluded.fetched_at
        """,
        niche_slug,
        json.dumps(items),
    )
