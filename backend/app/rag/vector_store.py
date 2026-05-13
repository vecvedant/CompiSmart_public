"""Qdrant client wrapper.

Design: one shared collection, partitioned by session_id in the payload.
We could use one collection per session, but that wastes collection overhead
on Qdrant Cloud free tier and makes cleanup awkward. Filtering by session_id
on every query is cheap.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from app.config import settings
from app.models import Chunk, VideoSlot
from app.rag.embeddings import embed_dim, embed_texts

log = logging.getLogger(__name__)

COLLECTION = "rag_returns_v1"


def _client() -> QdrantClient:
    if not settings.qdrant_url:
        raise RuntimeError("QDRANT_URL is not set in .env")
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        prefer_grpc=False,
        timeout=30.0,
    )


def ensure_collection() -> None:
    client = _client()
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION not in existing:
        log.info("Creating Qdrant collection %s (dim=%d)", COLLECTION, embed_dim())
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=embed_dim(), distance=Distance.COSINE),
        )
    # Payload indexes are required on Qdrant Cloud before filtering on a key.
    # Idempotent: re-creating an existing index is a no-op.
    # `platform` + `video_id` are needed for the per-video cache lookup
    # (load_video_cache), in addition to the existing session/slot/kind keys
    # for transcript+comment retrieval. `asset_id` is the v2 generalized
    # retrieval key — assets/processor.py tags every chunk with it.
    for field in ("session_id", "video_slot", "kind", "platform", "video_id", "asset_id"):
        try:
            client.create_payload_index(
                collection_name=COLLECTION,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
                wait=True,
            )
        except Exception as e:  # noqa: BLE001 — index may already exist
            log.debug("create_payload_index(%s) skipped: %s", field, e)


def upsert_chunks(session_id: str, video_id: str, chunks: list[Chunk]) -> int:
    if not chunks:
        return 0
    ensure_collection()
    client = _client()
    vectors = embed_texts([c.text for c in chunks])
    points = []
    for chunk, vec in zip(chunks, vectors):
        payload = {
            "session_id": session_id,
            "video_id": video_id,
            "video_slot": chunk.video_slot,
            "chunk_idx": chunk.chunk_idx,
            "kind": chunk.kind,
            "text": chunk.text,
        }
        if chunk.start_sec is not None:
            payload["start_sec"] = chunk.start_sec
        if chunk.end_sec is not None:
            payload["end_sec"] = chunk.end_sec
        if chunk.comment_likes is not None:
            payload["comment_likes"] = chunk.comment_likes
        if chunk.comment_replies is not None:
            payload["comment_replies"] = chunk.comment_replies
        points.append(
            PointStruct(id=str(uuid.uuid4()), vector=vec, payload=payload)
        )
    client.upsert(collection_name=COLLECTION, points=points, wait=True)
    return len(points)


def search(
    session_id: str,
    query_vector: list[float],
    *,
    video_slot: Optional[VideoSlot] = None,
    kind: Optional[str] = None,
    limit: int = 3,
) -> list[dict]:
    """Filtered similarity search. Returns list of payload dicts (with score)."""
    must = [FieldCondition(key="session_id", match=MatchValue(value=session_id))]
    if video_slot is not None:
        must.append(FieldCondition(key="video_slot", match=MatchValue(value=video_slot)))
    if kind is not None:
        must.append(FieldCondition(key="kind", match=MatchValue(value=kind)))

    client = _client()
    res = client.query_points(
        collection_name=COLLECTION,
        query=query_vector,
        query_filter=Filter(must=must),
        limit=limit,
        with_payload=True,
    )
    out = []
    for point in res.points:
        d = dict(point.payload or {})
        d["score"] = point.score
        out.append(d)
    return out


def list_chunks(
    session_id: str,
    *,
    video_slot: VideoSlot,
    kind: str,
    limit: int = 50,
) -> list[dict]:
    """Enumerate stored chunks for one session+slot+kind, ordered by chunk_idx.

    Used by the Sources panel to render transcript bits and comments without
    relying on similarity search. Returns payload dicts (no scores).
    """
    client = _client()
    must = [
        FieldCondition(key="session_id", match=MatchValue(value=session_id)),
        FieldCondition(key="video_slot", match=MatchValue(value=video_slot)),
        FieldCondition(key="kind", match=MatchValue(value=kind)),
    ]
    try:
        results, _ = client.scroll(
            collection_name=COLLECTION,
            scroll_filter=Filter(must=must),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as e:  # noqa: BLE001 -- empty list on error
        log.warning("list_chunks(%s/%s/%s) failed: %s", session_id, video_slot, kind, e)
        return []
    payloads = [dict(r.payload or {}) for r in results]
    payloads.sort(key=lambda p: p.get("chunk_idx") or 0)
    return payloads


# ---------- v2 asset-aware upsert & search --------------------------------
#
# Generalized retrieval: chunks are tagged with `asset_id` (a Supabase asset
# UUID) instead of (session_id, video_slot). The legacy A/B compare flow
# *also* writes asset rows now, so its chunks are reachable via both the
# old and new APIs.

def upsert_asset_chunks(
    asset_id: str,
    session_id: str,
    chunks: list[dict],
) -> int:
    """Upsert a batch of asset chunks.

    Each chunk dict must contain:
      - text (str)
      - kind (str): 'article_body' | 'transcript' | 'comment'
      - chunk_idx (int)
    Optional: start_sec, end_sec, comment_likes, comment_replies, niche_slug.

    Embeds all texts at once and writes one point per chunk with payload
    tagging both `asset_id` (new) and `session_id` (kept for legacy filters
    and for delete-session cleanup).
    """
    if not chunks:
        return 0
    ensure_collection()
    client = _client()
    vectors = embed_texts([c["text"] for c in chunks])
    points: list[PointStruct] = []
    for ch, vec in zip(chunks, vectors):
        payload = {
            "asset_id": asset_id,
            "session_id": session_id,
            "kind": ch["kind"],
            "chunk_idx": ch["chunk_idx"],
            "text": ch["text"],
        }
        for opt in ("start_sec", "end_sec", "comment_likes", "comment_replies", "niche_slug"):
            if ch.get(opt) is not None:
                payload[opt] = ch[opt]
        points.append(PointStruct(id=str(uuid.uuid4()), vector=vec, payload=payload))
    client.upsert(collection_name=COLLECTION, points=points, wait=True)
    return len(points)


def search_assets(
    asset_ids: list[str],
    query_vector: list[float],
    *,
    kind: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """Similarity search restricted to one or more asset_ids.

    Returns payload dicts (with `score`). When `asset_ids` is empty,
    returns []."""
    if not asset_ids:
        return []
    must = [FieldCondition(key="asset_id", match=MatchAny(any=list(asset_ids)))]
    if kind is not None:
        must.append(FieldCondition(key="kind", match=MatchValue(value=kind)))

    client = _client()
    res = client.query_points(
        collection_name=COLLECTION,
        query=query_vector,
        query_filter=Filter(must=must),
        limit=limit,
        with_payload=True,
    )
    out = []
    for point in res.points:
        d = dict(point.payload or {})
        d["score"] = point.score
        out.append(d)
    return out


def delete_asset(asset_id: str) -> None:
    """Remove all chunks belonging to one asset (when the user deletes it)."""
    client = _client()
    client.delete(
        collection_name=COLLECTION,
        points_selector=Filter(
            must=[FieldCondition(key="asset_id", match=MatchValue(value=asset_id))]
        ),
        wait=True,
    )


def copy_asset_chunks(source_asset_id: str, target_asset_id: str, target_session_id: str) -> int:
    """Clone all Qdrant points from one asset_id to another.

    Used when a new asset is a cross-session cache hit on an already-ingested
    URL — we skip extraction + re-embedding and just duplicate the existing
    vectors under the new asset_id / session_id. Much faster than re-running
    the pipeline (no Gemini embedding calls, no chunking, no trafilatura).
    """
    client = _client()
    collected: list = []
    offset = None
    # Scroll through all source chunks (paginated).
    while True:
        results, offset = client.scroll(
            collection_name=COLLECTION,
            scroll_filter=Filter(
                must=[FieldCondition(key="asset_id", match=MatchValue(value=source_asset_id))]
            ),
            limit=200,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        collected.extend(results)
        if offset is None:
            break
    if not collected:
        log.info("copy_asset_chunks: no source chunks for %s", source_asset_id)
        return 0

    new_points: list[PointStruct] = []
    for p in collected:
        payload = dict(p.payload or {})
        payload["asset_id"] = target_asset_id
        payload["session_id"] = target_session_id
        new_points.append(
            PointStruct(id=str(uuid.uuid4()), vector=p.vector, payload=payload)
        )
    client.upsert(collection_name=COLLECTION, points=new_points, wait=True)
    log.info(
        "copy_asset_chunks: cloned %d chunks %s -> %s",
        len(new_points), source_asset_id, target_asset_id,
    )
    return len(new_points)


def delete_session(session_id: str) -> None:
    client = _client()
    client.delete(
        collection_name=COLLECTION,
        points_selector=Filter(
            must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))]
        ),
        wait=True,
    )


# ---------- Session-metadata persistence ----------------------------------
#
# Cloud Run scales horizontally, and our in-memory `sessions.py` dict doesn't
# survive across container instances. We stash VideoMeta JSON in Qdrant on a
# zero-vector point so the chat handler can recover the session even if it
# lands on a fresh instance. Costs ~1.5 KB/session in Qdrant payload + the
# 384-dim zero vector. Free 1 GB tier holds a million of these.
#
# A real production deployment would use Redis (or even just a Cloud Memory-
# store instance) -- but that's $5+/mo and we're $0-budget. Qdrant is
# already wired and free, so reuse it.

_SESSION_META_KIND = "session_meta"


def save_session_metadata(session_id: str, meta_a_json: str, meta_b_json: str) -> None:
    """Upsert a single point holding both VideoMetas as JSON strings.

    The point uses session_id as its UUID-derived id so re-ingest replaces
    rather than duplicates. Vector is all zeros (semantic search will never
    match it because we always filter `kind` to transcript or comment).
    """
    ensure_collection()
    client = _client()
    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"session-meta:{session_id}"))
    client.upsert(
        collection_name=COLLECTION,
        points=[
            PointStruct(
                id=point_id,
                vector=[0.0] * embed_dim(),
                payload={
                    "session_id": session_id,
                    "kind": _SESSION_META_KIND,
                    "meta_a_json": meta_a_json,
                    "meta_b_json": meta_b_json,
                },
            )
        ],
        wait=True,
    )


def load_session_metadata(session_id: str) -> tuple[str, str] | None:
    """Fetch the JSON-encoded VideoMetas. Returns (meta_a_json, meta_b_json)
    or None if the session was never ingested (or has expired)."""
    client = _client()
    try:
        results, _ = client.scroll(
            collection_name=COLLECTION,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="session_id", match=MatchValue(value=session_id)),
                    FieldCondition(key="kind", match=MatchValue(value=_SESSION_META_KIND)),
                ]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as e:  # noqa: BLE001 -- treat all errors as miss
        log.warning("load_session_metadata(%s) failed: %s", session_id, e)
        return None
    if not results:
        return None
    payload = results[0].payload or {}
    a = payload.get("meta_a_json")
    b = payload.get("meta_b_json")
    if not a or not b:
        return None
    return a, b


# ---------- Per-video cache (transcript + comments + enrichment) ----------
#
# A given YouTube/Instagram video doesn't change between sessions: its
# transcript, top comments, sentiment, keywords, and trend status are the
# same whether ingested today or tomorrow. We cache the EXPENSIVE bits
# (transcript fetch via Deepgram/Apify, comments scrape, Gemini sentiment,
# Gemini keywords) keyed by `video_id`. The CHEAP bits (yt-dlp/Apify
# metadata pull -- views, likes, etc.) are always re-fetched so the
# numbers are current.
#
# Effect: re-ingesting the same URL completes in ~5-10 seconds (just the
# metadata refresh + chunk re-embedding) instead of 60-90 seconds.
# Side benefit: zero new Apify/Deepgram/Gemini calls for cache hits.
#
# TTL: 7 days (long enough to cover the demo cycle, short enough that
# a transcript correction or new top comments will eventually flow through).

_VIDEO_CACHE_KIND = "video_cache"
_VIDEO_CACHE_TTL_SECONDS = 7 * 24 * 3600


def _video_cache_point_id(platform: str, video_id: str) -> str:
    """Deterministic UUID so re-cache replaces the same point."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"video-cache:{platform}:{video_id}"))


def save_video_cache(
    platform: str,
    video_id: str,
    *,
    segments_json: str,
    comments_json: str,
    keywords_json: str,
    sentiment_json: str,
    trend_status: str,
) -> None:
    """Cache the expensive parts of an ingest, keyed by (platform, video_id).

    All inputs are pre-serialized JSON strings -- callers do their own
    Pydantic dump so this function stays dependency-free.
    """
    ensure_collection()
    client = _client()
    import time
    point_id = _video_cache_point_id(platform, video_id)
    client.upsert(
        collection_name=COLLECTION,
        points=[
            PointStruct(
                id=point_id,
                vector=[0.0] * embed_dim(),
                payload={
                    "kind": _VIDEO_CACHE_KIND,
                    "platform": platform,
                    "video_id": video_id,
                    "cached_at": int(time.time()),
                    "segments_json": segments_json,
                    "comments_json": comments_json,
                    "keywords_json": keywords_json,
                    "sentiment_json": sentiment_json,
                    "trend_status": trend_status,
                },
            )
        ],
        wait=True,
    )


def load_video_cache(platform: str, video_id: str) -> dict | None:
    """Return the cached payload dict for (platform, video_id), or None if
    no cache exists or the entry is older than the TTL."""
    client = _client()
    try:
        results, _ = client.scroll(
            collection_name=COLLECTION,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="kind", match=MatchValue(value=_VIDEO_CACHE_KIND)),
                    FieldCondition(key="platform", match=MatchValue(value=platform)),
                    FieldCondition(key="video_id", match=MatchValue(value=video_id)),
                ]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as e:  # noqa: BLE001 -- treat as miss
        log.warning("load_video_cache(%s/%s) failed: %s", platform, video_id, e)
        return None
    if not results:
        return None
    payload = results[0].payload or {}
    import time
    cached_at = int(payload.get("cached_at") or 0)
    if cached_at and (time.time() - cached_at) > _VIDEO_CACHE_TTL_SECONDS:
        log.info("video cache HIT but EXPIRED for %s/%s", platform, video_id)
        return None
    log.info("video cache HIT for %s/%s (cached %ds ago)", platform, video_id, int(time.time() - cached_at))
    return dict(payload)
