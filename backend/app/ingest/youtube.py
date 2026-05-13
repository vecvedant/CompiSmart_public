"""YouTube ingester: YouTube Data API for metadata, Apify (pintostudio) for transcript.

Both yt-dlp and youtube-transcript-api fail on Cloud Run because YouTube
blocks datacenter IPs. So:

  - Metadata        -> YouTube Data API v3 (videos.list + channels.list).
                       yt-dlp kept as a last-ditch fallback that, in
                       practice, only works locally (cookie issues kill it
                       in production).
  - Transcript      -> `pintostudio/youtube-transcript-scraper` via Apify,
                       called directly. No fallback chain — if it errors,
                       the asset goes to status=failed and the user sees
                       the reason.
  - Comments        -> see comments.py (Data API primary, yt-dlp fallback).
  - Instagram       -> see instagram.py (unrelated, Apify + Deepgram).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import yt_dlp

from app.ingest.apify_client import scrape_youtube_transcript
from app.ingest.detect import extract_youtube_id
from app.ingest.errors import IngestError
from app.ingest.metrics import engagement_rate, life_stage
from app.ingest.youtube_data_api import fetch_metadata_for_videometa
from app.models import TranscriptSegment, VideoMeta, VideoSlot

log = logging.getLogger(__name__)

_HASHTAG_RE = re.compile(r"#(\w+)")

# yt-dlp options for the fallback metadata path. Kept for symmetry; on
# Cloud Run this path will normally fail with a cookie / 403 error.
_YDL_OPTS_META = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": False,
    "format": "bestaudio/best/worst",
    "ignore_no_formats_error": True,
}


# ---------- Helpers -------------------------------------------------------


def _parse_upload_date_yyyymmdd(s: Any) -> datetime | None:
    """yt-dlp returns upload_date as a YYYYMMDD string."""
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%Y%m%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _extract_hashtags(description: str | None, tags: list[str] | None) -> list[str]:
    """Combine #-tags from the description with the API/yt-dlp tags field.
    Dedupe case-insensitively, cap to 25.
    """
    out: list[str] = []
    if description:
        out.extend(_HASHTAG_RE.findall(description))
    if tags:
        out.extend(t for t in tags if isinstance(t, str))
    seen: set[str] = set()
    clean: list[str] = []
    for t in out:
        k = t.lower().lstrip("#")
        if k and k not in seen:
            seen.add(k)
            clean.append(k)
    return clean[:25]


# ---------- Apify transcript parser ---------------------------------------


def _parse_apify_transcript(item: dict[str, Any]) -> list[TranscriptSegment]:
    """Parse pintostudio/youtube-transcript-scraper output.

    The actor's output schema isn't perfectly documented and varies by
    version; we read multiple possible field names defensively.
    """
    transcript = (
        item.get("transcript")
        or item.get("captions")
        or item.get("data")
        or item.get("subtitles")
        or []
    )

    segments: list[TranscriptSegment] = []
    if isinstance(transcript, list):
        for entry in transcript:
            if not isinstance(entry, dict):
                continue
            text = (entry.get("text") or "").strip()
            if not text:
                continue
            try:
                start = float(entry.get("start") or entry.get("offset") or 0.0)
                dur = float(entry.get("dur") or entry.get("duration") or 0.0)
            except (TypeError, ValueError):
                continue
            segments.append(
                TranscriptSegment(text=text, start_sec=start, end_sec=start + dur)
            )

    if segments:
        return segments

    # Fallback: actor returned the full text as a single string.
    full_text = item.get("text") or item.get("transcriptText") or ""
    if isinstance(full_text, str) and full_text.strip():
        return [TranscriptSegment(text=full_text.strip(), start_sec=0.0, end_sec=0.0)]

    raise IngestError("Apify transcript scraper returned no usable transcript data")


# ---------- yt-dlp metadata fallback --------------------------------------


def _ytdlp_metadata_fallback(url: str) -> dict[str, Any] | None:
    """Last-ditch yt-dlp metadata. Will fail on Cloud Run cookie checks;
    kept so local dev / unit tests still work.
    """
    try:
        with yt_dlp.YoutubeDL(_YDL_OPTS_META) as ydl:
            info = ydl.extract_info(url, download=False)
        if info:
            return info
    except Exception as e:  # noqa: BLE001 — fallback must never raise
        log.warning("yt-dlp metadata fallback failed for %s: %s", url, e)
    return None


# ---------- Public API ----------------------------------------------------


def fetch_youtube_metadata(url: str, slot: VideoSlot) -> tuple[VideoMeta, str]:
    """Metadata via YouTube Data API v3 (primary), yt-dlp (fallback).

    Always re-fetched per ingest so views/likes reflect right now (the
    cache-aware pipeline reuses transcript + enrichment, not live counts).
    """
    video_id = extract_youtube_id(url)

    # Primary: YouTube Data API v3
    try:
        d = fetch_metadata_for_videometa(video_id)
        log.info("YT Data API metadata OK for %s (views=%d)", video_id, d.get("views") or 0)
        return _videometa_from_data_api(url, video_id, slot, d), video_id
    except Exception as e:  # noqa: BLE001 — try yt-dlp before failing
        log.warning("YT Data API metadata failed for %s (%s); trying yt-dlp", video_id, e)

    # Fallback: yt-dlp (expected to fail on Cloud Run)
    info = _ytdlp_metadata_fallback(url)
    if not info:
        raise IngestError(f"Could not fetch YouTube metadata for {url} (both Data API and yt-dlp failed)")
    return _videometa_from_ytdlp(url, video_id, slot, info), video_id


def fetch_youtube_transcript(url: str) -> list[TranscriptSegment]:
    """Transcript via pintostudio/youtube-transcript-scraper. No fallback.

    The fallback chain (free youtube-transcript-api, yt-dlp+Deepgram) was
    removed in v2 because both fail on Cloud Run for the same IP-block
    reason. pintostudio uses residential IPs through Apify and bypasses
    YouTube's datacenter blocks.
    """
    video_id = extract_youtube_id(url)
    log.info("YouTube transcript via pintostudio actor for %s", video_id)
    item = scrape_youtube_transcript(url)
    return _parse_apify_transcript(item)


def ingest_youtube(url: str, slot: VideoSlot) -> tuple[VideoMeta, list[TranscriptSegment]]:
    """Backwards-compatible: metadata + transcript in one call.
    Used by smoke_youtube.py and any non-cache-aware caller."""
    meta, _ = fetch_youtube_metadata(url, slot)
    segments = fetch_youtube_transcript(url)
    log.info("YouTube ingest: slot=%s id=%s segs=%d", slot, meta.video_id, len(segments))
    return meta, segments


# ---------- Internal: VideoMeta builders ----------------------------------


def _videometa_from_data_api(url: str, video_id: str, slot: VideoSlot, d: dict[str, Any]) -> VideoMeta:
    views = d.get("views") or 0
    likes = d.get("likes") or 0
    comments = d.get("comments") or 0
    upload_date = d.get("upload_date")  # already a datetime or None

    age_days: int | None = None
    view_velocity: float | None = None
    if upload_date is not None:
        age_days = max(1, (datetime.now(timezone.utc) - upload_date).days)
        view_velocity = views / age_days if age_days else None

    return VideoMeta(
        slot=slot,
        platform="youtube",
        url=url,
        video_id=video_id,
        title=d.get("title"),
        creator=d.get("channel_title") or "unknown",
        follower_count=d.get("follower_count"),
        views=views,
        likes=likes,
        comments=comments,
        hashtags=_extract_hashtags(d.get("description"), d.get("tags")),
        upload_date=upload_date,
        duration_sec=d.get("duration_sec"),
        thumbnail_url=d.get("thumbnail_url"),
        engagement_rate=engagement_rate(views, likes, comments),
        age_days=age_days,
        view_velocity=view_velocity,
        life_stage=life_stage(age_days),
    )


def _videometa_from_ytdlp(url: str, video_id: str, slot: VideoSlot, info: dict[str, Any]) -> VideoMeta:
    views = int(info.get("view_count") or 0)
    likes = int(info.get("like_count") or 0)
    comments = int(info.get("comment_count") or 0)
    upload_date = _parse_upload_date_yyyymmdd(info.get("upload_date"))

    age_days: int | None = None
    view_velocity: float | None = None
    if upload_date is not None:
        age_days = max(1, (datetime.now(timezone.utc) - upload_date).days)
        view_velocity = views / age_days if age_days else None

    return VideoMeta(
        slot=slot,
        platform="youtube",
        url=url,
        video_id=video_id,
        title=info.get("title"),
        creator=info.get("uploader") or info.get("channel") or "unknown",
        follower_count=int(info.get("channel_follower_count") or 0) or None,
        views=views,
        likes=likes,
        comments=comments,
        hashtags=_extract_hashtags(info.get("description"), info.get("tags")),
        upload_date=upload_date,
        duration_sec=float(info["duration"]) if info.get("duration") else None,
        thumbnail_url=info.get("thumbnail"),
        engagement_rate=engagement_rate(views, likes, comments),
        age_days=age_days,
        view_velocity=view_velocity,
        life_stage=life_stage(age_days),
    )
