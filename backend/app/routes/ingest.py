"""POST /api/ingest -- accepts two URLs, ingests both, returns session metadata.

Cache-aware pipeline per video:
  1. Detect platform + extract video_id (instant).
  2. Pull live metadata (yt-dlp / Apify reel) -- always fresh so views/likes
     reflect right now.
  3. Check Qdrant for a cached (transcript + comments + sentiment + keywords +
     trend) bundle keyed by video_id. TTL = 7 days.
  4a. CACHE HIT: skip the expensive enrichment entirely. Use cached transcript,
      cached comments, cached enrichment fields. Apply to the fresh metadata.
      Net latency: 5-10s per video instead of 60-90s.
  4b. CACHE MISS: fetch transcript (Deepgram / Apify YT scraper) and run the
      enrichment phases (comments, sentiment, keywords, trend). Save the
      bundle to the cache for next time.
  5. Chunk + embed + upsert to Qdrant. Always done -- needs fresh session_id.
"""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException

from app import sessions
from app.ingest.chunking import chunk_transcript
from app.ingest.comments import (
    classify_sentiment,
    discussion_depth,
    fetch_top_comments,
)
from app.ingest.detect import detect_platform
from app.ingest.errors import IngestError
from app.ingest.instagram import (
    fetch_instagram_metadata,
    fetch_instagram_transcript,
)
from app.ingest.trends import extract_keywords, topic_trend_status
from app.ingest.youtube import fetch_youtube_metadata, fetch_youtube_transcript
from app.models import (
    Chunk,
    Comment,
    CommentSentimentMix,
    IngestRequest,
    IngestResponse,
    TranscriptSegment,
    VideoMeta,
    VideoSlot,
)
from app.rag.vector_store import (
    load_video_cache,
    save_video_cache,
    upsert_chunks,
)

log = logging.getLogger(__name__)
router = APIRouter()

_ingest_lock = asyncio.Semaphore(1)
# 2 workers caps concurrent SDK clients in memory (was 4 -- contributed to
# the 1 GiB OOMs).
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ingest")


# ---------- Per-video work, cache-aware -----------------------------------

async def _to_thread(fn, *args):
    """Shorthand for `loop.run_in_executor(_executor, fn, *args)`."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, fn, *args)


def _apply_cached_enrichment(meta: VideoMeta, cache: dict) -> tuple[VideoMeta, list[TranscriptSegment], list[Comment]]:
    """Hydrate VideoMeta fields + segments + comments from a cache hit."""
    segments = [TranscriptSegment(**s) for s in json.loads(cache["segments_json"])]
    comments = [Comment(**c) for c in json.loads(cache["comments_json"])]
    keywords = json.loads(cache["keywords_json"]) or []
    sentiment_dict = json.loads(cache.get("sentiment_json") or "{}") or {}

    meta.top_comments = comments
    meta.discussion_depth = discussion_depth(comments)
    meta.comment_sentiment_mix = (
        CommentSentimentMix(**sentiment_dict) if sentiment_dict else None
    )
    meta.topic_keywords = keywords
    meta.topic_trend_status = cache.get("trend_status") or "unavailable"
    return meta, segments, comments


async def _run_enrichment(
    meta: VideoMeta, segments: list[TranscriptSegment]
) -> tuple[VideoMeta, list[Comment]]:
    """Cache-miss path: comments + keywords -> sentiment + trend."""
    transcript_text = " ".join(s.text for s in segments)

    comments_fut = _to_thread(fetch_top_comments, meta.url)
    keywords_fut = _to_thread(extract_keywords, transcript_text)
    comments, keywords = await asyncio.gather(comments_fut, keywords_fut)

    sentiment_fut = _to_thread(classify_sentiment, comments)
    trend_fut = _to_thread(topic_trend_status, keywords)
    sentiment, trend = await asyncio.gather(sentiment_fut, trend_fut)

    meta.top_comments = comments
    meta.discussion_depth = discussion_depth(comments)
    meta.comment_sentiment_mix = sentiment
    meta.topic_keywords = keywords
    meta.topic_trend_status = trend
    return meta, comments


def _save_to_cache(
    meta: VideoMeta,
    segments: list[TranscriptSegment],
    comments: list[Comment],
) -> None:
    """Persist the expensive bits so the next ingest of the same video skips
    Apify/Deepgram/Gemini entirely. Best-effort -- never fail the request."""
    try:
        save_video_cache(
            meta.platform,
            meta.video_id,
            segments_json=json.dumps([s.model_dump() for s in segments]),
            comments_json=json.dumps([c.model_dump() for c in comments]),
            keywords_json=json.dumps(meta.topic_keywords),
            sentiment_json=(
                meta.comment_sentiment_mix.model_dump_json()
                if meta.comment_sentiment_mix
                else "{}"
            ),
            trend_status=meta.topic_trend_status,
        )
    except Exception as e:  # noqa: BLE001 -- cache writes never fail the request
        log.warning("save_video_cache(%s/%s) failed: %s", meta.platform, meta.video_id, e)


async def _fetch_one_with_cache(
    url: str, slot: VideoSlot
) -> tuple[VideoMeta, list[TranscriptSegment], list[Comment]]:
    """End-to-end per-video pipeline. Always runs fresh metadata; reuses
    cached transcript + enrichment when available."""
    platform = detect_platform(url)

    # Step 1: live metadata (always fresh)
    if platform == "youtube":
        meta, video_id = await _to_thread(fetch_youtube_metadata, url, slot)
    elif platform == "instagram":
        meta, video_id, media_url = await _to_thread(
            fetch_instagram_metadata, url, slot
        )
    else:
        raise IngestError(f"Unsupported platform: {platform}")

    # Step 2: cache lookup
    cache = await _to_thread(load_video_cache, platform, video_id)
    if cache:
        log.info("CACHE HIT for slot=%s %s/%s -- skipping transcript + enrichment",
                 slot, platform, video_id)
        meta, segments, comments = _apply_cached_enrichment(meta, cache)
        return meta, segments, comments

    log.info("CACHE MISS for slot=%s %s/%s -- full pipeline", slot, platform, video_id)

    # Step 3a: transcript (slow)
    if platform == "youtube":
        segments = await _to_thread(fetch_youtube_transcript, url)
    else:  # instagram
        segments = await _to_thread(fetch_instagram_transcript, media_url)

    # Step 3b: enrichment (slow, parallelizable)
    meta, comments = await _run_enrichment(meta, segments)

    # Step 4: persist cache for next time
    _save_to_cache(meta, segments, comments)

    return meta, segments, comments


def _comments_to_chunks(comments: list[Comment], slot: VideoSlot) -> list[Chunk]:
    out: list[Chunk] = []
    for i, c in enumerate(comments):
        out.append(
            Chunk(
                video_slot=slot,
                chunk_idx=i,
                kind="comment",
                text=c.text,
                comment_likes=c.likes,
                comment_replies=c.replies,
            )
        )
    return out


@router.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest) -> IngestResponse:
    async with _ingest_lock:
        session_id = uuid.uuid4().hex[:12]
        log.info("Ingest session=%s url_a=%s url_b=%s", session_id, req.url_a, req.url_b)

        # Both videos run end-to-end in parallel: cache lookup, transcript
        # fetch (only on miss), and enrichment all happen concurrently for
        # A and B. This is the biggest win of the cache-aware refactor --
        # on a fresh session both miss and full ingest takes ~max(A, B)
        # instead of A+B; on subsequent ingests both hit and the whole
        # request finishes in ~10s.
        try:
            (meta_a, segs_a, comments_a), (meta_b, segs_b, comments_b) = await asyncio.gather(
                _fetch_one_with_cache(req.url_a, "A"),
                _fetch_one_with_cache(req.url_b, "B"),
            )
        except IngestError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        # Chunk + embed + upsert (always runs -- new session_id every time).
        transcript_chunks_a = chunk_transcript(segs_a, video_slot="A")
        transcript_chunks_b = chunk_transcript(segs_b, video_slot="B")
        comment_chunks_a = _comments_to_chunks(comments_a, slot="A")
        comment_chunks_b = _comments_to_chunks(comments_b, slot="B")

        chunks_a = transcript_chunks_a + comment_chunks_a
        chunks_b = transcript_chunks_b + comment_chunks_b

        n_a, n_b = await asyncio.gather(
            _to_thread(upsert_chunks, session_id, meta_a.video_id, chunks_a),
            _to_thread(upsert_chunks, session_id, meta_b.video_id, chunks_b),
        )
        log.info(
            "Stored chunks: A=%d (transcript=%d comment=%d) B=%d (transcript=%d comment=%d) session=%s",
            n_a,
            len(transcript_chunks_a),
            len(comment_chunks_a),
            n_b,
            len(transcript_chunks_b),
            len(comment_chunks_b),
            session_id,
        )

        sessions.save(session_id, meta_a, meta_b)

        # Force a GC pass after the request completes. Apify response dicts,
        # yt-dlp info dicts, and per-thread SDK clients create cyclic
        # references the gen-0/1 collector won't catch immediately; this
        # releases ~50-100 MB on the way out and helps avoid OOMs on
        # follow-up ingests.
        gc.collect()

        return IngestResponse(session_id=session_id, video_a=meta_a, video_b=meta_b)
