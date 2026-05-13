"""NewsAPI news fetcher.

v1 demo: NewsAPI only. RSS support is wired in the niches taxonomy + the
helpers below, but `fetch_news()` currently skips RSS to keep the request
budget small and the implementation surface tight. Flip ENABLE_RSS to True
when you want the extra coverage — the helpers are kept here, not deleted.

NewsAPI gives us editorially-curated top headlines per category with a
generous 100 req/day free quota — plenty for ~12 niches refreshed every 6h
(~50 calls/day).

Returns `FeedItem(type="news")`. The aggregator dedupes by canonical URL.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.models import FeedItem
from app.niches import Niche

log = logging.getLogger(__name__)

NEWSAPI_BASE = "https://newsapi.org/v2/top-headlines"
NEWSAPI_TIMEOUT_S = 8.0
RSS_TIMEOUT_S = 6.0
RSS_PER_FEED_LIMIT = 8
NEWSAPI_PAGE_SIZE = 15

# Toggle to add RSS items into the feed.
ENABLE_RSS = False


# ---------------------------------------------------------------------------
# NewsAPI
# ---------------------------------------------------------------------------

async def fetch_newsapi(niche: Niche) -> list[FeedItem]:
    if not settings.newsapi_key:
        return []
    if not niche.newsapi_category:
        # No category mapping → use keyword query instead.
        query = " OR ".join(niche.search_keywords[:3])
        params = {"q": query, "language": "en", "pageSize": NEWSAPI_PAGE_SIZE}
    else:
        params = {
            "category": niche.newsapi_category,
            "language": "en",
            "pageSize": NEWSAPI_PAGE_SIZE,
        }

    params["apiKey"] = settings.newsapi_key

    try:
        async with httpx.AsyncClient(timeout=NEWSAPI_TIMEOUT_S) as client:
            r = await client.get(NEWSAPI_BASE, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("NewsAPI fetch failed for niche=%s: %s", niche.slug, e)
        return []

    out: list[FeedItem] = []
    for art in data.get("articles", []):
        url = art.get("url")
        if not url:
            continue
        out.append(FeedItem(
            type="news",
            title=(art.get("title") or "").strip(),
            url=url,
            source=(art.get("source") or {}).get("name") or _domain(url),
            published_at=_parse_iso(art.get("publishedAt")),
            summary=(art.get("description") or "").strip(),
            thumbnail=art.get("urlToImage"),
        ))
    log.info("NewsAPI niche=%s -> %d items", niche.slug, len(out))
    return out


# ---------------------------------------------------------------------------
# RSS
# ---------------------------------------------------------------------------

async def fetch_rss_for_niche(niche: Niche) -> list[FeedItem]:
    if not niche.rss_feeds:
        return []
    tasks = [fetch_one_rss(url) for url in niche.rss_feeds]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    items: list[FeedItem] = []
    for res in results:
        if isinstance(res, Exception):
            continue
        items.extend(res)
    return items


async def fetch_one_rss(feed_url: str) -> list[FeedItem]:
    """Fetch + parse one RSS feed. feedparser is sync, so off-thread it."""
    try:
        async with httpx.AsyncClient(timeout=RSS_TIMEOUT_S) as client:
            r = await client.get(feed_url, follow_redirects=True)
            r.raise_for_status()
            body = r.text
    except Exception as e:
        log.debug("RSS fetch failed %s: %s", feed_url, e)
        return []

    parsed = await asyncio.to_thread(_parse_rss, body)
    out: list[FeedItem] = []
    for entry in parsed[:RSS_PER_FEED_LIMIT]:
        link = entry.get("link")
        title = entry.get("title")
        if not link or not title:
            continue
        out.append(FeedItem(
            type="news",
            title=title.strip(),
            url=link,
            source=_domain(link),
            published_at=entry.get("published_at"),
            summary=(entry.get("summary") or "").strip(),
            thumbnail=entry.get("thumbnail"),
        ))
    return out


def _parse_rss(body: str) -> list[dict]:
    # Lazy import — feedparser is heavy and we want module-import to stay fast.
    import feedparser
    parsed = feedparser.parse(body)
    out = []
    for e in getattr(parsed, "entries", []):
        published_at: Optional[datetime] = None
        struct = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
        if struct:
            try:
                published_at = datetime(*struct[:6], tzinfo=timezone.utc)
            except Exception:
                published_at = None

        thumbnail = None
        # media:thumbnail or media:content
        for key in ("media_thumbnail", "media_content"):
            val = getattr(e, key, None)
            if val and isinstance(val, list) and val:
                thumbnail = val[0].get("url")
                if thumbnail:
                    break

        out.append({
            "link": getattr(e, "link", None),
            "title": getattr(e, "title", None),
            "summary": getattr(e, "summary", "") or "",
            "published_at": published_at,
            "thumbnail": thumbnail,
        })
    return out


# ---------------------------------------------------------------------------
# Combined entry point
# ---------------------------------------------------------------------------

async def fetch_news(niche: Niche) -> list[FeedItem]:
    """NewsAPI only by default. RSS is gated behind ENABLE_RSS."""
    if not ENABLE_RSS:
        return await fetch_newsapi(niche)
    api_task = asyncio.create_task(fetch_newsapi(niche))
    rss_task = asyncio.create_task(fetch_rss_for_niche(niche))
    api_items, rss_items = await asyncio.gather(api_task, rss_task)
    return api_items + rss_items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # NewsAPI uses "2024-10-30T12:34:56Z"
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""
