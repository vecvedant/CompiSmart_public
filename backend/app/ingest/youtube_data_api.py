"""YouTube Data API v3 client for metadata + comments.

Replaces yt-dlp for YouTube data fetching because yt-dlp gets IP-blocked
on Cloud Run datacenter ranges. The Data API works from anywhere because
it's authenticated by API key, not IP.

Uses the YT_DATA_API key (separate from the Gemini key) — see config.py.

Quotas (free tier, 10000 units/day):
  videos.list        =  1 unit / call
  channels.list      =  1 unit / call
  commentThreads.list = 1 unit / call
At ~3 units per video, that's ~3000 video ingests/day on free tier.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.config import settings
from app.models import Comment

log = logging.getLogger(__name__)

YT_API_BASE = "https://www.googleapis.com/youtube/v3"
YT_TIMEOUT_S = 10.0


def _api_key() -> str:
    """Use the dedicated YT Data API key, fall back to the Gemini key.
    Raises if neither is set."""
    key = settings.yt_data_api_key or settings.google_api_key
    if not key:
        raise RuntimeError(
            "YT_DATA_API (or GOOGLE_API_KEY) is not set. The YouTube Data API "
            "v3 key is required for video metadata and comments."
        )
    return key


def _iso_to_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _parse_iso_duration(iso: Optional[str]) -> Optional[float]:
    """PT5M30S → 330.0 seconds. Best-effort parser; returns None on bad input."""
    if not iso or not iso.startswith("PT"):
        return None
    total = 0.0
    num = ""
    for ch in iso[2:]:
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


# ---------------------------------------------------------------------------
# videos.list
# ---------------------------------------------------------------------------

def fetch_video_metadata(video_id: str) -> dict[str, Any]:
    """Return the raw API response for one video (snippet + statistics +
    contentDetails). Caller picks the fields it needs.

    Raises RuntimeError on HTTP error or empty result.
    """
    params = {
        "key": _api_key(),
        "id": video_id,
        "part": "snippet,statistics,contentDetails",
    }
    with httpx.Client(timeout=YT_TIMEOUT_S) as client:
        r = client.get(f"{YT_API_BASE}/videos", params=params)
        r.raise_for_status()
        data = r.json()
    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"YouTube Data API returned no items for video {video_id}")
    return items[0]


def fetch_channel_stats(channel_id: str) -> dict[str, Any]:
    """Channel subscriber count + view count. Best-effort: returns {} on error
    rather than raising — the follower count is a nice-to-have, not critical.
    """
    if not channel_id:
        return {}
    try:
        params = {
            "key": _api_key(),
            "id": channel_id,
            "part": "snippet,statistics",
        }
        with httpx.Client(timeout=YT_TIMEOUT_S) as client:
            r = client.get(f"{YT_API_BASE}/channels", params=params)
            r.raise_for_status()
            data = r.json()
        items = data.get("items") or []
        return items[0] if items else {}
    except Exception as e:
        log.warning("channels.list failed for %s: %s", channel_id, e)
        return {}


def _int_or_none(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# commentThreads.list
# ---------------------------------------------------------------------------

def fetch_top_comments(video_id: str, max_results: int = 10) -> list[Comment]:
    """Top-level comments via commentThreads.list, ordered by relevance.

    Returns [] on any failure (comments are non-critical). Disabled comments,
    private videos, and quota-exceeded all silently return [].
    """
    params = {
        "key": _api_key(),
        "videoId": video_id,
        "part": "snippet",
        "maxResults": max(1, min(100, max_results)),
        "order": "relevance",
        "textFormat": "plainText",
    }
    try:
        with httpx.Client(timeout=YT_TIMEOUT_S) as client:
            r = client.get(f"{YT_API_BASE}/commentThreads", params=params)
            if r.status_code in (403, 404):
                # 403 = comments disabled or quota; 404 = bad video id.
                log.info("commentThreads %d for %s (likely disabled)", r.status_code, video_id)
                return []
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("commentThreads.list failed for %s: %s", video_id, e)
        return []

    out: list[Comment] = []
    for item in data.get("items", []):
        snip = ((item.get("snippet") or {}).get("topLevelComment") or {}).get("snippet") or {}
        text = (snip.get("textDisplay") or snip.get("textOriginal") or "").strip()
        if not text:
            continue
        out.append(
            Comment(
                text=text[:1500],
                likes=_int_or_none(snip.get("likeCount")) or 0,
                replies=_int_or_none(((item.get("snippet") or {}).get("totalReplyCount"))) or 0,
                author=snip.get("authorDisplayName"),
            )
        )
        if len(out) >= max_results:
            break
    out.sort(key=lambda c: c.likes, reverse=True)
    return out[:max_results]


# ---------------------------------------------------------------------------
# Convenience: assemble normalized fields for the VideoMeta constructor.
# ---------------------------------------------------------------------------

def fetch_metadata_for_videometa(video_id: str) -> dict[str, Any]:
    """One call to videos.list + (optional) one call to channels.list.

    Returns a flat dict with keys our VideoMeta wants:
      title, description, channel_title, channel_id, follower_count,
      views, likes, comments, upload_date (datetime), duration_sec,
      thumbnail_url, tags, hashtags
    """
    item = fetch_video_metadata(video_id)
    snip = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    content = item.get("contentDetails") or {}
    thumbs = (snip.get("thumbnails") or {})
    thumb = (
        (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {})
        .get("url")
    )

    channel_id = snip.get("channelId")
    channel = fetch_channel_stats(channel_id) if channel_id else {}
    follower_count = None
    if channel:
        cstats = channel.get("statistics") or {}
        follower_count = _int_or_none(cstats.get("subscriberCount"))

    return {
        "title": snip.get("title"),
        "description": snip.get("description") or "",
        "channel_title": snip.get("channelTitle"),
        "channel_id": channel_id,
        "follower_count": follower_count,
        "views": _int_or_none(stats.get("viewCount")) or 0,
        "likes": _int_or_none(stats.get("likeCount")) or 0,
        "comments": _int_or_none(stats.get("commentCount")) or 0,
        "upload_date": _iso_to_dt(snip.get("publishedAt")),
        "duration_sec": _parse_iso_duration(content.get("duration")),
        "thumbnail_url": thumb,
        "tags": snip.get("tags") or [],
    }
