"""Instagram Reels ingester: Apify metadata -> Deepgram transcript.

Apify abstracts the cookie/login/rate-limit pain that yt-dlp would otherwise
inflict on us for IG. The reel scraper returns a media URL we hand directly
to Deepgram, so Render's bandwidth and RAM stay out of the audio path.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.ingest.apify_client import scrape_profile, scrape_reel
from app.ingest.deepgram_client import transcribe_url
from app.ingest.detect import extract_instagram_shortcode
from app.ingest.errors import IngestError
from app.ingest.metrics import engagement_rate, life_stage
from app.models import TranscriptSegment, VideoMeta, VideoSlot

log = logging.getLogger(__name__)

_HASHTAG_RE = re.compile(r"#(\w+)")


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        # Apify returns "2024-01-15T12:34:56.000Z" or similar
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _first(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Get the first non-null value among the given keys."""
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return default


def _extract_hashtags(item: dict[str, Any]) -> list[str]:
    raw: list[str] = []
    tags = item.get("hashtags") or []
    if isinstance(tags, list):
        raw.extend(t for t in tags if isinstance(t, str))
    caption = item.get("caption") or ""
    raw.extend(_HASHTAG_RE.findall(caption))
    seen: set[str] = set()
    out: list[str] = []
    for t in raw:
        k = t.lower().lstrip("#")
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out[:25]


def _extract_follower_count(reel: dict[str, Any]) -> int | None:
    """Try multiple shapes the Apify IG scraper has used over time."""
    # Top-level keys
    for key in ("ownerFollowersCount", "followersCount", "followers_count"):
        v = reel.get(key)
        if isinstance(v, int) and v >= 0:
            return v
    # Nested owner object
    owner = reel.get("owner") or {}
    if isinstance(owner, dict):
        for key in ("followers_count", "followersCount", "follower_count"):
            v = owner.get(key)
            if isinstance(v, int) and v >= 0:
                return v
    return None


def fetch_instagram_metadata(url: str, slot: VideoSlot) -> tuple[VideoMeta, str, str]:
    """Fast path: Apify reel scrape only (no Deepgram).
    Returns (VideoMeta, shortcode, media_url).

    Used by the cache-aware pipeline -- always re-fetched for fresh
    view/like counts. The media_url is returned so the caller can hand
    it to Deepgram on cache miss.
    """
    shortcode = extract_instagram_shortcode(url)
    if not shortcode:
        raise IngestError(f"Could not parse shortcode from {url!r}")

    reel = scrape_reel(url)
    media_url = _first(reel, "videoUrl", "video_url")
    if not media_url:
        raise IngestError(f"Apify returned no video URL for {url}; is the reel public?")

    creator = _first(reel, "ownerUsername", "owner_username") or "unknown"
    follower_count = _extract_follower_count(reel)
    if follower_count is None and creator != "unknown":
        try:
            profile = scrape_profile(creator)
            follower_count = profile.get("followersCount") or profile.get("followers_count")
        except Exception as e:  # noqa: BLE001 -- profile is best-effort
            log.warning("Profile scrape for %s failed; follower_count=None: %s", creator, e)

    views = int(_first(reel, "videoPlayCount", "videoViewCount", "playsCount", default=0) or 0)
    likes = int(_first(reel, "likesCount", "likes_count", default=0) or 0)
    comments = int(_first(reel, "commentsCount", "comments_count", default=0) or 0)
    upload_date = _parse_iso(_first(reel, "timestamp", "takenAtTimestamp"))

    age_days: int | None = None
    view_velocity: float | None = None
    if upload_date is not None:
        age_days = max(1, (datetime.now(timezone.utc) - upload_date).days)
        view_velocity = views / age_days if age_days else None

    duration = reel.get("videoDuration")
    if duration is not None:
        try:
            duration = float(duration)
        except (TypeError, ValueError):
            duration = None

    meta = VideoMeta(
        slot=slot,
        platform="instagram",
        url=url,
        video_id=shortcode,
        title=(reel.get("caption") or "")[:120] or None,
        creator=creator,
        follower_count=follower_count,
        views=views,
        likes=likes,
        comments=comments,
        hashtags=_extract_hashtags(reel),
        upload_date=upload_date,
        duration_sec=duration,
        thumbnail_url=_first(reel, "displayUrl", "thumbnailUrl"),
        engagement_rate=engagement_rate(views, likes, comments),
        age_days=age_days,
        view_velocity=view_velocity,
        life_stage=life_stage(age_days),
    )
    return meta, shortcode, media_url


def fetch_instagram_transcript(media_url: str) -> list[TranscriptSegment]:
    """Slow path: send Apify-supplied media URL to Deepgram. Cache miss only."""
    return transcribe_url(media_url)


def ingest_instagram(url: str, slot: VideoSlot) -> tuple[VideoMeta, list[TranscriptSegment]]:
    """Backwards-compatible: metadata + transcript in one call.
    Used by smoke_instagram.py and any non-cache-aware caller."""
    meta, _, media_url = fetch_instagram_metadata(url, slot)
    log.info("Instagram ingest: slot=%s id=%s, sending to Deepgram", slot, meta.video_id)
    segments = fetch_instagram_transcript(media_url)
    return meta, segments
