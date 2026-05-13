"""Asset processor: extract → chunk → embed → upsert → mark ready.

Two asset types today:

  article — httpx + trafilatura body extraction, paragraph-aware chunking.
            All steps blocking but fast (~3-5s end-to-end).

  video   — reuses the existing video ingest helpers (youtube.py /
            instagram.py + Qdrant 7-day video cache). Splits work into
            critical (transcript + embedding → chat-ready) and background
            (comments + sentiment + keywords + trend → fills in async)
            so the asset is searchable in ~10-15s on a cache miss.
"""
from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app import supabase_client
from app.assets.text_chunker import chunk_article
from app.db import url_cache as url_cache_db
from app.feed.article_extractor import extract_article
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
from app.models import Asset, Comment, CommentSentimentMix, TranscriptSegment, VideoMeta
from app.rag.vector_store import (
    copy_asset_chunks,
    load_video_cache,
    save_video_cache,
    upsert_asset_chunks,
)

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="asset-proc")


async def _to_thread(fn, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, fn, *args)


# ---------------------------------------------------------------------------
# Public entrypoints
# ---------------------------------------------------------------------------

async def process_asset(asset_row: dict) -> None:
    """Dispatch on asset type, with a cross-session URL cache shortcut.

    Cache flow (before any expensive work):
      1. Compute canonical_url from source_url.
      2. Look up the most recent READY asset with the same canonical_url
         (from any session). If found within the TTL, clone:
            - body_text, title (if empty), summary, metadata_json
            - all Qdrant chunks (re-tagged with the new asset_id + session)
         → mark ready in 1-2s instead of 10-90s.
      3. If no cache hit, run the normal pipeline; this asset itself
         becomes the cache for future sessions.
    """
    asset_id = asset_row["id"]
    asset_type = asset_row["type"]
    src = asset_row.get("source_url") or ""

    # Try cache hit first (only meaningful for article/video — note has no URL).
    if src and asset_type in ("article", "video"):
        try:
            if await _try_cache_clone(asset_row):
                return
        except Exception as e:
            # Cache lookup must NEVER block ingest. Log and fall through.
            log.warning("cache clone failed for %s, falling through: %s", asset_id, e)

    try:
        if asset_type == "article":
            await _process_article(asset_row)
        elif asset_type == "video":
            await _process_video(asset_row)
        elif asset_type == "note":
            await _process_note(asset_row)
        else:
            raise ValueError(f"unsupported asset type for processing: {asset_type}")
        await supabase_client.update_asset(asset_id, {"ingest_status": "ready"})
    except Exception as e:
        log.exception("process_asset failed id=%s: %s", asset_id, e)
        await supabase_client.update_asset(
            asset_id,
            {"ingest_status": "failed", "metadata_json": {**(asset_row.get("metadata_json") or {}), "error": str(e)[:500]}},
        )


async def _try_cache_clone(asset_row: dict) -> bool:
    """Return True if we cloned from cache and the asset is now ready."""
    src = asset_row.get("source_url") or ""
    canonical = url_cache_db.canonical_url(src)
    if not canonical:
        return False
    cached = await url_cache_db.find_cached(canonical)
    if not cached or cached["id"] == asset_row["id"]:
        return False

    log.info(
        "Cache HIT for asset %s (canonical=%s, source=%s)",
        asset_row["id"], canonical, cached["id"],
    )

    # 1) Copy the textual + metadata content into the new row.
    cached_meta = cached.get("metadata_json") or {}
    patch = {
        "body_text": cached.get("body_text"),
        "summary": (cached.get("summary") or asset_row.get("summary") or "")[:5000],
        "metadata_json": {
            **(asset_row.get("metadata_json") or {}),
            **cached_meta,
            "cached_from_asset_id": cached["id"],
            "cached_at": asset_row.get("added_at") or "",
        },
        "ingest_status": "ready",
    }
    # Only adopt the cached title if the user didn't pre-set one (feed item titles
    # are usually nicer than raw URLs).
    if not (asset_row.get("title") and len(asset_row["title"]) > 5) and cached.get("title"):
        patch["title"] = cached["title"][:300]
    await supabase_client.update_asset(asset_row["id"], patch)

    # 2) Clone Qdrant chunks under the new asset_id (no embedding calls).
    try:
        n = await _to_thread(
            copy_asset_chunks, cached["id"], asset_row["id"], asset_row["session_id"],
        )
        log.info("Cloned %d chunks from cache for asset=%s", n, asset_row["id"])
    except Exception as e:
        # If chunk clone fails, fall back to full re-ingest so chat retrieval
        # still works for this asset.
        log.warning("chunk clone failed (%s); will re-ingest", e)
        await supabase_client.update_asset(
            asset_row["id"], {"ingest_status": "pending"}
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Article
# ---------------------------------------------------------------------------

async def _process_article(asset_row: dict) -> None:
    """Article ingest with graceful fallback.

    Some sites (paywalled, geofenced, bot-blocked) return 403/empty. Rather
    than mark the asset failed and leave a broken card in the sidebar, we
    fall back to chunking the title+summary so the asset is at least
    chat-able and citable. The metadata flags `extraction_failed` so the
    UI can show a "limited content" indicator if it wants.
    """
    asset_id = asset_row["id"]
    session_id = asset_row["session_id"]
    url = asset_row.get("source_url")
    if not url:
        raise ValueError("article asset missing source_url")

    body, title = await extract_article(url)

    extraction_failed = False
    if not body:
        # Fall back: stitch together whatever we DO have (title + summary)
        # so the asset still has indexable content and the user isn't stuck
        # with a "failed" card. Real-world sites that 403 us: Bloomberg, FT,
        # nltimes, some paywalled regionals.
        feed_title = (asset_row.get("title") or "").strip()
        feed_summary = (asset_row.get("summary") or "").strip()
        fallback = f"{feed_title}\n\n{feed_summary}".strip()
        if not fallback:
            raise ValueError("article body extraction failed and no fallback content")
        body = fallback
        extraction_failed = True
        log.info("Article %s using fallback (title+summary, %d chars)", asset_id, len(body))

    chunks_text = chunk_article(body)
    if not chunks_text:
        # Even tiny content should chunk; if not, fall back to single chunk.
        chunks_text = [body]

    chunks = [
        {
            "text": t,
            "kind": "article_body",
            "chunk_idx": i,
            "niche_slug": asset_row.get("niche_slug"),
        }
        for i, t in enumerate(chunks_text)
    ]
    n = await _to_thread(upsert_asset_chunks, asset_id, session_id, chunks)
    log.info("Article asset %s -> %d chunks indexed%s",
             asset_id, n, " (fallback content)" if extraction_failed else "")

    patch: dict = {
        "body_text": body[:50000],
        "metadata_json": {
            **(asset_row.get("metadata_json") or {}),
            "extraction_failed": extraction_failed,
        },
    }
    if title and not asset_row.get("title"):
        patch["title"] = title[:300]
    if not asset_row.get("summary"):
        patch["summary"] = (body[:280] + "…") if len(body) > 280 else body
    await supabase_client.update_asset(asset_id, patch)


# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------

async def _process_video(asset_row: dict) -> None:
    """Video asset: critical path (transcript+embed) → ready;
    enrichment (comments + sentiment + keywords + trend) → fired in background.
    """
    asset_id = asset_row["id"]
    session_id = asset_row["session_id"]
    url = asset_row.get("source_url")
    if not url:
        raise ValueError("video asset missing source_url")

    platform = detect_platform(url)

    # --- live metadata (always fresh) ---
    if platform == "youtube":
        meta, video_id = await _to_thread(fetch_youtube_metadata, url, "A")
        media_url = None
    elif platform == "instagram":
        meta, video_id, media_url = await _to_thread(fetch_instagram_metadata, url, "A")
    else:
        raise IngestError(f"Unsupported platform: {platform}")

    # Persist metadata RIGHT NOW so the asset card has title / creator /
    # views even if transcript fails downstream. Without this, a failed
    # asset shows no useful info — bad UX when Apify is having a bad day.
    await _persist_video_meta(asset_id, asset_row, meta, segments=[])

    # --- cache lookup ---
    cache = await _to_thread(load_video_cache, platform, video_id)

    if cache:
        segments, comments = _apply_cached(meta, cache)
        log.info("Video asset cache HIT %s/%s -> %d segments, %d comments",
                 platform, video_id, len(segments), len(comments))
        await _index_video_chunks(asset_id, session_id, segments, comments, asset_row.get("niche_slug"))
        await _persist_video_meta(asset_id, asset_row, meta, segments)
        return

    # --- cache miss: transcript first (critical) ---
    log.info("Video asset cache MISS %s/%s -- transcript first", platform, video_id)
    if platform == "youtube":
        segments = await _to_thread(fetch_youtube_transcript, url)
    else:
        segments = await _to_thread(fetch_instagram_transcript, media_url)

    # Index transcript chunks immediately so chat works.
    await _index_video_chunks(asset_id, session_id, segments, [], asset_row.get("niche_slug"))
    await _persist_video_meta(asset_id, asset_row, meta, segments)

    # --- enrichment in background ---
    asyncio.create_task(
        _enrich_video_async(
            asset_id, session_id, asset_row.get("niche_slug"),
            platform, video_id, url, meta, segments,
        )
    )


async def _enrich_video_async(
    asset_id: str,
    session_id: str,
    niche_slug: Optional[str],
    platform: str,
    video_id: str,
    url: str,
    meta: VideoMeta,
    segments: list[TranscriptSegment],
) -> None:
    """Background-fired enrichment. Failures are logged but never bubble up."""
    try:
        transcript_text = " ".join(s.text for s in segments)

        comments_fut = _to_thread(fetch_top_comments, url)
        keywords_fut = _to_thread(extract_keywords, transcript_text)
        comments, keywords = await asyncio.gather(comments_fut, keywords_fut)

        sentiment_fut = _to_thread(classify_sentiment, comments)
        trend_fut = _to_thread(topic_trend_status, keywords)
        sentiment, trend = await asyncio.gather(sentiment_fut, trend_fut)

        # Index comment chunks now that we have them.
        await _upsert_comment_chunks(asset_id, session_id, comments, niche_slug)

        # Persist enrichment to the asset row metadata.
        meta.top_comments = comments
        meta.discussion_depth = discussion_depth(comments)
        meta.comment_sentiment_mix = sentiment
        meta.topic_keywords = keywords
        meta.topic_trend_status = trend
        await supabase_client.update_asset(
            asset_id,
            {"metadata_json": _meta_to_json(meta)},
        )

        # Save to 7-day cross-session cache.
        try:
            save_video_cache(
                platform, video_id,
                segments_json=json.dumps([s.model_dump() for s in segments]),
                comments_json=json.dumps([c.model_dump() for c in comments]),
                keywords_json=json.dumps(keywords),
                sentiment_json=sentiment.model_dump_json() if sentiment else "{}",
                trend_status=trend,
            )
        except Exception as e:
            log.warning("video cache save failed: %s", e)

        log.info("Background enrichment done asset=%s", asset_id)
    except Exception as e:
        log.exception("Background enrichment FAILED asset=%s: %s", asset_id, e)


async def _index_video_chunks(
    asset_id: str,
    session_id: str,
    segments: list[TranscriptSegment],
    comments: list[Comment],
    niche_slug: Optional[str],
) -> None:
    transcript_chunks = chunk_transcript(segments, video_slot="A")
    chunk_dicts: list[dict] = [
        {
            "text": c.text,
            "kind": "transcript",
            "chunk_idx": c.chunk_idx,
            "start_sec": c.start_sec,
            "end_sec": c.end_sec,
            "niche_slug": niche_slug,
        }
        for c in transcript_chunks
    ]
    n_t = await _to_thread(upsert_asset_chunks, asset_id, session_id, chunk_dicts)
    log.info("Indexed transcript: %d chunks asset=%s", n_t, asset_id)

    if comments:
        await _upsert_comment_chunks(asset_id, session_id, comments, niche_slug)


async def _upsert_comment_chunks(
    asset_id: str,
    session_id: str,
    comments: list[Comment],
    niche_slug: Optional[str],
) -> None:
    if not comments:
        return
    chunk_dicts = [
        {
            "text": c.text,
            "kind": "comment",
            "chunk_idx": i,
            "comment_likes": c.likes,
            "comment_replies": c.replies,
            "niche_slug": niche_slug,
        }
        for i, c in enumerate(comments)
    ]
    n = await _to_thread(upsert_asset_chunks, asset_id, session_id, chunk_dicts)
    log.info("Indexed %d comment chunks asset=%s", n, asset_id)


async def _persist_video_meta(
    asset_id: str,
    asset_row: dict,
    meta: VideoMeta,
    segments: list[TranscriptSegment],
) -> None:
    body = " ".join(s.text for s in segments)
    patch = {
        "body_text": body[:50000],
        "metadata_json": _meta_to_json(meta),
    }
    if not asset_row.get("title") and meta.title:
        patch["title"] = meta.title[:300]
    if not asset_row.get("summary"):
        patch["summary"] = (body[:280] + "…") if len(body) > 280 else body
    await supabase_client.update_asset(asset_id, patch)


def _apply_cached(meta: VideoMeta, cache: dict) -> tuple[list[TranscriptSegment], list[Comment]]:
    segments = [TranscriptSegment(**s) for s in json.loads(cache["segments_json"])]
    comments = [Comment(**c) for c in json.loads(cache["comments_json"])]
    sentiment_dict = json.loads(cache.get("sentiment_json") or "{}") or {}
    meta.top_comments = comments
    meta.discussion_depth = discussion_depth(comments)
    meta.comment_sentiment_mix = (
        CommentSentimentMix(**sentiment_dict) if sentiment_dict else None
    )
    meta.topic_keywords = json.loads(cache.get("keywords_json") or "[]") or []
    meta.topic_trend_status = cache.get("trend_status") or "unavailable"
    return segments, comments


def _meta_to_json(meta: VideoMeta) -> dict:
    """Compact projection of VideoMeta into the asset metadata_json column."""
    return {
        "platform": meta.platform,
        "video_id": meta.video_id,
        "creator": meta.creator,
        "follower_count": meta.follower_count,
        "views": meta.views,
        "likes": meta.likes,
        "comments": meta.comments,
        "engagement_rate": meta.engagement_rate,
        "life_stage": meta.life_stage,
        "upload_date": meta.upload_date.isoformat() if meta.upload_date else None,
        "duration_sec": meta.duration_sec,
        "thumbnail_url": meta.thumbnail_url,
        "hashtags": meta.hashtags,
        "topic_keywords": meta.topic_keywords,
        "topic_trend_status": meta.topic_trend_status,
        "discussion_depth": meta.discussion_depth,
        "comment_sentiment_mix": (
            meta.comment_sentiment_mix.model_dump() if meta.comment_sentiment_mix else None
        ),
        "top_comments": [c.model_dump() for c in (meta.top_comments or [])][:10],
    }


# ---------------------------------------------------------------------------
# Note
# ---------------------------------------------------------------------------

async def _process_note(asset_row: dict) -> None:
    asset_id = asset_row["id"]
    session_id = asset_row["session_id"]
    body = (asset_row.get("body_text") or asset_row.get("summary") or "").strip()
    if not body:
        raise ValueError("note asset missing body_text/summary")
    chunks_text = chunk_article(body)
    chunks = [
        {"text": t, "kind": "article_body", "chunk_idx": i, "niche_slug": asset_row.get("niche_slug")}
        for i, t in enumerate(chunks_text)
    ]
    n = await _to_thread(upsert_asset_chunks, asset_id, session_id, chunks)
    log.info("Note asset %s -> %d chunks", asset_id, n)
