"""HackerNews feed source via Algolia's HN Search API.

Public, free, no auth. We hit the `search_by_date` endpoint with a query
formed from the niche's search keywords, filtered to stories (no comments
or polls) from the last 7 days, sorted by points.

Niches opt in via `use_hackernews=True` in niches.py (currently: tech,
finance, science). For other niches, HN noise outweighs signal.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.models import FeedItem
from app.niches import Niche

log = logging.getLogger(__name__)

HN_BASE = "https://hn.algolia.com/api/v1"
HN_TIMEOUT_S = 6.0
HN_HITS = 10


async def fetch_hackernews(niche: Niche) -> list[FeedItem]:
    if not niche.use_hackernews:
        return []
    query = " ".join(niche.search_keywords[:3])
    since = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp())
    params = {
        "query": query,
        "tags": "story",
        "numericFilters": f"created_at_i>{since}",
        "hitsPerPage": HN_HITS,
    }
    try:
        async with httpx.AsyncClient(timeout=HN_TIMEOUT_S) as client:
            r = await client.get(f"{HN_BASE}/search", params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("HN fetch failed for niche=%s: %s", niche.slug, e)
        return []

    out: list[FeedItem] = []
    for hit in data.get("hits", []):
        title = (hit.get("title") or hit.get("story_title") or "").strip()
        url = hit.get("url") or (
            f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            if hit.get("objectID") else None
        )
        if not title or not url:
            continue
        out.append(FeedItem(
            type="news",
            title=title[:240],
            url=url,
            source="HackerNews",
            published_at=_parse_ts(hit.get("created_at")),
            summary="",  # HN search returns no body
            thumbnail=None,
            view_count=hit.get("points") or None,    # reuse for ranking
            channel=hit.get("author"),
        ))
    log.info("HN niche=%s -> %d stories", niche.slug, len(out))
    return out


def _parse_ts(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None
