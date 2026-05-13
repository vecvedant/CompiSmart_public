"""POST /api/compare  — create a two-video compare session from saved assets.

The existing two-video flow (verdict.py, sources.py, the legacy
build_chain_for_session) expects an in-memory `sessions.save(session_id, meta_a, meta_b)`
shape with VideoMeta objects. We rebuild that shape from two video assets:

  1. Look up both assets in Supabase (must be type=video, ingest_status=ready).
  2. Recreate VideoMeta from metadata_json + url + title.
  3. Re-tag the Qdrant chunks for this compare session_id with video_slot A/B.
     (Cleanest is to re-upsert as A/B chunks; cheapest is to query by asset_id.
     We pick the latter — extend search/verdict/sources to fall back to asset_id
     if no video_slot chunks exist.)

For v1 simplicity we go even lighter: create a fresh compare-session_id,
re-embed the two videos' transcripts under that session_id with slots A/B
(reusing the cached transcript from the asset row), so the existing
verdict/sources routes work unchanged.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException

from app import sessions, supabase_client
from app.ingest.chunking import chunk_transcript
from app.models import (
    Comment,
    CommentSentimentMix,
    CompareRequest,
    TranscriptSegment,
    VideoMeta,
)
from app.rag.vector_store import upsert_chunks
from app.rag.verdict import build_verdict
from app.routes.ingest import _comments_to_chunks  # tiny helper reuse

log = logging.getLogger(__name__)
router = APIRouter()


def _segments_from_body(body: str) -> list[TranscriptSegment]:
    """We only stored body_text (transcript joined with spaces) for video assets,
    so we approximate segments by splitting on sentences. Verdict + sources
    don't critically depend on per-second timing for the prose; the citation
    chips will just show a rougher window.
    """
    if not body:
        return []
    sentences = [s.strip() for s in body.replace("\n", " ").split(". ") if s.strip()]
    seg_dur = 6.0
    out: list[TranscriptSegment] = []
    t = 0.0
    for s in sentences:
        out.append(TranscriptSegment(text=s + (". " if not s.endswith(".") else ""),
                                      start_sec=t, end_sec=t + seg_dur))
        t += seg_dur
    return out


def _videometa_from_asset(asset: dict, slot: str) -> VideoMeta:
    meta = asset.get("metadata_json") or {}

    sentiment = None
    if meta.get("comment_sentiment_mix"):
        try:
            sentiment = CommentSentimentMix(**meta["comment_sentiment_mix"])
        except Exception:
            sentiment = None

    top_comments = []
    for c in (meta.get("top_comments") or [])[:10]:
        try:
            top_comments.append(Comment(**c))
        except Exception:
            continue

    upload_date: Optional[datetime] = None
    raw_date = meta.get("upload_date")
    if raw_date:
        try:
            upload_date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
        except Exception:
            upload_date = None

    return VideoMeta(
        slot=slot,                   # type: ignore[arg-type]
        platform=meta.get("platform") or "youtube",
        url=asset.get("source_url") or "",
        video_id=meta.get("video_id") or "",
        title=asset.get("title"),
        creator=meta.get("creator") or "",
        follower_count=meta.get("follower_count"),
        views=meta.get("views") or 0,
        likes=meta.get("likes") or 0,
        comments=meta.get("comments") or 0,
        hashtags=meta.get("hashtags") or [],
        upload_date=upload_date,
        duration_sec=meta.get("duration_sec"),
        thumbnail_url=meta.get("thumbnail_url"),
        engagement_rate=meta.get("engagement_rate") or 0.0,
        life_stage=meta.get("life_stage"),
        topic_keywords=meta.get("topic_keywords") or [],
        topic_trend_status=meta.get("topic_trend_status") or "unavailable",
        discussion_depth=meta.get("discussion_depth"),
        comment_sentiment_mix=sentiment,
        top_comments=top_comments,
    )


@router.post("/compare")
async def create_compare(req: CompareRequest) -> dict:
    if not supabase_client.is_configured():
        raise HTTPException(503, "Supabase not configured")

    rows = await supabase_client.list_assets(req.session_id)
    by_id = {r["id"]: r for r in rows}
    a = by_id.get(req.asset_a_id)
    b = by_id.get(req.asset_b_id)
    if not a or not b:
        raise HTTPException(404, "one or both assets not found in session")
    for x, label in ((a, "A"), (b, "B")):
        if x.get("type") != "video":
            raise HTTPException(400, f"asset {label} is not a video")
        if x.get("ingest_status") != "ready":
            raise HTTPException(409, f"asset {label} is not ready yet (status={x.get('ingest_status')})")

    compare_session_id = uuid.uuid4().hex[:12]
    meta_a = _videometa_from_asset(a, "A")
    meta_b = _videometa_from_asset(b, "B")

    # Rebuild A/B-tagged chunks under the new compare-session id so verdict.py
    # and sources.py work without modification.
    segs_a = _segments_from_body(a.get("body_text") or "")
    segs_b = _segments_from_body(b.get("body_text") or "")
    # Smaller target tokens for compare: body_text is already the joined
    # transcript (often 1-3K chars), so target=400 gives one chunk per video,
    # leaving the Sources panel almost empty. Use 150 to get 3-6 chunks per
    # side — same total context, better surface area for citations.
    chunks_a = chunk_transcript(segs_a, video_slot="A", target_tokens=150, overlap_tokens=30) if segs_a else []
    chunks_b = chunk_transcript(segs_b, video_slot="B", target_tokens=150, overlap_tokens=30) if segs_b else []
    chunks_a += _comments_to_chunks(meta_a.top_comments, slot="A")
    chunks_b += _comments_to_chunks(meta_b.top_comments, slot="B")

    try:
        await asyncio.gather(
            asyncio.to_thread(upsert_chunks, compare_session_id, meta_a.video_id, chunks_a),
            asyncio.to_thread(upsert_chunks, compare_session_id, meta_b.video_id, chunks_b),
        )
    except Exception as e:
        log.exception("compare upsert failed: %s", e)
        raise HTTPException(500, f"upsert failed: {e}")

    sessions.save(compare_session_id, meta_a, meta_b)

    # Prewarm the verdict so the InsightPanel loads instantly when the user
    # opens it. build_verdict caches in-process; failure is non-fatal.
    asyncio.create_task(_safe_prewarm_verdict(compare_session_id))

    log.info("compare session=%s assets=(%s, %s)", compare_session_id, a["id"], b["id"])
    return {
        "compare_session_id": compare_session_id,
        "video_a": meta_a.model_dump(mode="json"),
        "video_b": meta_b.model_dump(mode="json"),
    }


async def _safe_prewarm_verdict(session_id: str) -> None:
    try:
        await build_verdict(session_id)
    except Exception as e:
        log.warning("verdict prewarm failed for %s: %s", session_id, e)
