"""YouTube trending fetcher via Data API v3.

For each niche we run `search.list` filtered to the last 30 days, ordered by
viewCount, then hydrate stats with `videos.list`. Quota cost:
  search.list  = 100 units per call
  videos.list  =   1 unit per call
With 12 niches refreshed every 6h:  12 × 4 × (100+1) = ~4848 units/day,
well under the 10,000-unit free quota.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.config import settings
from app.models import FeedItem
from app.niches import Niche

log = logging.getLogger(__name__)

YT_API_BASE = "https://www.googleapis.com/youtube/v3"
YT_TIMEOUT_S = 8.0
YT_MAX_RESULTS = 15


async def fetch_trending(niche: Niche) -> list[FeedItem]:
    # YT Data API uses a dedicated key (different GCP project from Gemini).
    # Falls back to google_api_key if YT_DATA_API isn't set, for users with
    # a single combined key.
    api_key = settings.yt_data_api_key or settings.google_api_key
    if not api_key:
        log.warning("YT_DATA_API key missing, skipping YT trending for %s", niche.slug)
        return []

    query = " ".join(niche.search_keywords[:3])
    published_after = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")

    search_params = {
        "key": api_key,
        "part": "snippet",
        "type": "video",
        "q": query,
        "order": "viewCount",
        "publishedAfter": published_after,
        "maxResults": YT_MAX_RESULTS,
        "relevanceLanguage": "en",
        "safeSearch": "moderate",
    }
    if niche.yt_category_id:
        search_params["videoCategoryId"] = niche.yt_category_id

    try:
        async with httpx.AsyncClient(timeout=YT_TIMEOUT_S) as client:
            r = await client.get(f"{YT_API_BASE}/search", params=search_params)
            r.raise_for_status()
            search_data = r.json()

            video_ids = [
                item["id"]["videoId"]
                for item in search_data.get("items", [])
                if item.get("id", {}).get("videoId")
            ]
            if not video_ids:
                return []

            stats_params = {
                "key": api_key,
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(video_ids),
            }
            r2 = await client.get(f"{YT_API_BASE}/videos", params=stats_params)
            r2.raise_for_status()
            stats_data = r2.json()
    except Exception as e:
        log.warning("YT fetch failed for niche=%s: %s", niche.slug, e)
        return []

    out: list[FeedItem] = []
    for v in stats_data.get("items", []):
        vid = v.get("id")
        snip = v.get("snippet", {}) or {}
        stats = v.get("statistics", {}) or {}
        content = v.get("contentDetails", {}) or {}
        if not vid:
            continue
        thumbs = snip.get("thumbnails", {}) or {}
        thumb_url = (
            (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {})
            .get("url")
        )
        out.append(FeedItem(
            type="video",
            title=(snip.get("title") or "").strip(),
            url=f"https://www.youtube.com/watch?v={vid}",
            source="YouTube",
            published_at=_parse_iso(snip.get("publishedAt")),
            summary=(snip.get("description") or "")[:280].strip(),
            thumbnail=thumb_url,
            video_id=vid,
            channel=snip.get("channelTitle"),
            view_count=_int(stats.get("viewCount")),
            duration_sec=_parse_duration(content.get("duration")),
        ))
    log.info("YT trending niche=%s -> %d videos", niche.slug, len(out))
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _int(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _parse_duration(iso: Optional[str]) -> Optional[float]:
    """ISO 8601 duration like PT5M30S → seconds."""
    if not iso or not iso.startswith("PT"):
        return None
    s = iso[2:]
    total = 0.0
    num = ""
    for ch in s:
        if ch.isdigit():
            num += ch
        elif ch == "H":
            total += int(num or 0) * 3600
            num = ""
        elif ch == "M":
            total += int(num or 0) * 60
            num = ""
        elif ch == "S":
            total += int(num or 0)
            num = ""
    return total or None
