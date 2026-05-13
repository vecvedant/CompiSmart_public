"""Combine news + YT into a single ranked feed per niche, cached in Supabase.

Ranking: popularity_proxy × recency_decay
  popularity_proxy: log(view_count+1) for videos, fixed 1.0 for news
                    (news doesn't expose engagement on the feed level)
  recency_decay: exp(-age_hours / 48)  → half-life ~33h
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from app import supabase_client
from app.feed.hackernews_scraper import fetch_hackernews
from app.feed.news_scraper import fetch_news
from app.feed.reddit_scraper import fetch_reddit
from app.feed.youtube_trending import fetch_trending
from app.models import FeedItem
from app.niches import Niche

log = logging.getLogger(__name__)

CACHE_TTL_HOURS = 6
FEED_MAX_ITEMS = 40


async def get_feed(niche: Niche, force_refresh: bool = False) -> tuple[list[FeedItem], bool]:
    """Return (items, was_cached)."""
    if not force_refresh and supabase_client.is_configured():
        cached = await _load_cache(niche.slug)
        if cached is not None:
            return cached, True

    items = await _build_feed(niche)

    if supabase_client.is_configured():
        try:
            await supabase_client.upsert_feed_cache(
                niche.slug, [i.model_dump(mode="json") for i in items]
            )
        except Exception as e:
            log.warning("feed_cache upsert failed niche=%s: %s", niche.slug, e)

    return items, False


async def _load_cache(niche_slug: str) -> Optional[list[FeedItem]]:
    try:
        row = await supabase_client.fetch_feed_cache(niche_slug)
    except Exception as e:
        log.warning("feed_cache fetch failed niche=%s: %s", niche_slug, e)
        return None
    if not row:
        return None
    fetched_at = _parse_ts(row.get("fetched_at"))
    if not fetched_at:
        return None
    age_h = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
    if age_h > CACHE_TTL_HOURS:
        return None
    items = row.get("items_json") or []
    return [FeedItem.model_validate(i) for i in items]


async def _build_feed(niche: Niche) -> list[FeedItem]:
    # All 4 sources fan out in parallel. Failures are tolerated per-source.
    news_task = asyncio.create_task(fetch_news(niche))
    yt_task = asyncio.create_task(fetch_trending(niche))
    reddit_task = asyncio.create_task(fetch_reddit(niche))
    hn_task = asyncio.create_task(fetch_hackernews(niche))
    news, videos, reddit, hn = await asyncio.gather(
        news_task, yt_task, reddit_task, hn_task
    )

    combined = list(news) + list(videos) + list(reddit) + list(hn)
    deduped = _dedupe(combined)
    for item in deduped:
        item.score = _score(item)
    deduped.sort(key=lambda it: it.score, reverse=True)
    return deduped[:FEED_MAX_ITEMS]


def _dedupe(items: list[FeedItem]) -> list[FeedItem]:
    seen: set[str] = set()
    out: list[FeedItem] = []
    for it in items:
        key = _canonical_url(it.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _canonical_url(url: str) -> str:
    """Dedup key. Includes the query string because YouTube URLs differ ONLY
    in `?v=`, and without it every video collapses to youtube.com/watch.
    """
    try:
        u = urlparse(url)
        host = u.netloc.lower().replace("www.", "")
        return f"{host}{u.path.rstrip('/')}?{u.query}" if u.query else f"{host}{u.path.rstrip('/')}"
    except Exception:
        return url


def _score(item: FeedItem) -> float:
    """Mix popularity × recency.

    Per-source tuning:
      - video (YouTube): log(views), 14-day half-life — viral videos compound.
      - reddit:          log(upvotes), 3-day half-life — Reddit decays fast.
      - hackernews:      log(points), 2-day half-life — same logic.
      - news (NewsAPI):  flat 0.6 popularity (no engagement signal), 2-day half-life.
    """
    src = (item.source or "").lower()
    if item.type == "video":
        pop = math.log10((item.view_count or 0) + 10) / 6.0
        half_life_h = 14 * 24.0
    elif src.startswith("r/"):
        # view_count slot carries upvotes for reddit items
        pop = min(math.log10((item.view_count or 0) + 10) / 4.0, 1.3)
        half_life_h = 3 * 24.0
    elif src == "hackernews":
        pop = min(math.log10((item.view_count or 0) + 10) / 3.5, 1.3)
        half_life_h = 2 * 24.0
    else:
        pop = 0.6
        half_life_h = 2 * 24.0

    age_h = 24.0
    if item.published_at:
        try:
            now = datetime.now(timezone.utc)
            pub = item.published_at
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            age_h = max((now - pub).total_seconds() / 3600, 0.0)
        except Exception:
            pass
    recency = math.exp(-age_h / half_life_h)
    return pop * recency


def _parse_ts(s) -> Optional[datetime]:
    if not s:
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    try:
        s = str(s).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None
