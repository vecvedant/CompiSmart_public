"""Reddit feed source.

Pulls top posts from per-niche subreddits via Reddit's public JSON endpoint
(no OAuth required for read-only). Reddit rate-limits unauthenticated
traffic at ~60 req/min — we make at most 5-6 subreddit calls per niche
refresh (every 6h), so ~24 calls/hour worst case across all niches.

Reddit returns posts with:
  - title, url, permalink, author
  - score (upvotes)
  - num_comments
  - created_utc
  - selftext (for text posts; empty for link posts)

We surface text posts using their reddit URL (so chat can fetch the comment
thread later), and link posts using the linked URL so trafilatura can pull
the article body when the user adds it as an asset.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.models import FeedItem
from app.niches import Niche

log = logging.getLogger(__name__)

USER_AGENT = "compismart/0.2 (read-only feed aggregator)"
REDDIT_TIMEOUT_S = 6.0
PER_SUBREDDIT_LIMIT = 8


async def fetch_reddit(niche: Niche) -> list[FeedItem]:
    if not niche.subreddits:
        return []
    tasks = [_fetch_one_subreddit(sr) for sr in niche.subreddits]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: list[FeedItem] = []
    for r in results:
        if isinstance(r, Exception):
            continue
        out.extend(r)
    log.info("Reddit niche=%s -> %d posts across %d subs",
             niche.slug, len(out), len(niche.subreddits))
    return out


async def _fetch_one_subreddit(sub: str) -> list[FeedItem]:
    url = f"https://www.reddit.com/r/{sub}/top.json"
    params = {"t": "week", "limit": PER_SUBREDDIT_LIMIT}
    headers = {"User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(timeout=REDDIT_TIMEOUT_S, headers=headers) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.debug("reddit fetch failed sub=%s: %s", sub, e)
        return []

    out: list[FeedItem] = []
    for child in data.get("data", {}).get("children", []):
        d = child.get("data") or {}
        if d.get("stickied") or d.get("over_18"):
            continue
        title = (d.get("title") or "").strip()
        permalink = d.get("permalink") or ""
        post_url = f"https://www.reddit.com{permalink}" if permalink else None
        ext_url = d.get("url_overridden_by_dest") or d.get("url") or post_url
        if not ext_url or not title:
            continue
        is_self = bool(d.get("is_self"))
        # For self-posts (discussion threads), keep the Reddit URL — trafilatura
        # can extract the body. For link posts, use the linked article URL so
        # we get the source article when added as an asset.
        final_url = post_url if is_self else (ext_url or post_url)
        if not final_url:
            continue
        out.append(FeedItem(
            type="news",
            title=title[:240],
            url=final_url,
            source=f"r/{sub}",
            published_at=_parse_ts(d.get("created_utc")),
            summary=(d.get("selftext") or "")[:280].strip(),
            thumbnail=_pick_thumbnail(d),
            view_count=d.get("score") or None,        # reuse view_count for score (used by aggregator)
            channel=d.get("author"),
        ))
    return out


def _parse_ts(ts) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _pick_thumbnail(d: dict) -> Optional[str]:
    # Prefer high-res preview if Reddit gives us one.
    preview = d.get("preview") or {}
    images = preview.get("images") or []
    if images:
        src = (images[0].get("source") or {}).get("url")
        if src:
            # Reddit HTML-encodes ampersands in these URLs.
            return src.replace("&amp;", "&")
    thumb = d.get("thumbnail")
    if thumb and thumb.startswith("http"):
        return thumb
    return None
