"""Session store.

Keeps VideoMeta for each ingested session so the frontend can re-render the
cards without re-ingesting, and the chat handler can build the system prompt.

Two-layer design:
  1. In-memory dict (fast, instance-local)
  2. Qdrant-backed JSON payload (slow, but shared across Cloud Run instances)

Reads check memory first; on miss they fall through to Qdrant and re-hydrate
the local dict. Writes always go to BOTH layers, so the local cache is warm
on the instance that did the ingest, and other instances pull from Qdrant
when they need it. At real-prod multi-instance scale, swap the persistent
layer to Redis (Cloud Memorystore) for sub-ms latency -- Qdrant is fine for
the demo where new sessions are minutes apart.
"""

from __future__ import annotations

import logging
from threading import Lock

from app.models import VideoMeta
from app.rag.vector_store import load_session_metadata, save_session_metadata

log = logging.getLogger(__name__)

_lock = Lock()
_store: dict[str, dict[str, VideoMeta]] = {}


def save(session_id: str, video_a: VideoMeta, video_b: VideoMeta) -> None:
    """Write to both the in-memory cache AND the Qdrant durable layer."""
    with _lock:
        _store[session_id] = {"A": video_a, "B": video_b}
    try:
        save_session_metadata(
            session_id,
            video_a.model_dump_json(),
            video_b.model_dump_json(),
        )
    except Exception as e:  # noqa: BLE001 -- durable layer is best-effort
        log.warning(
            "save_session_metadata(%s) failed; in-memory cache only: %s",
            session_id, e,
        )


def get(session_id: str) -> dict[str, VideoMeta] | None:
    """Read-through: memory -> Qdrant. Re-hydrates the local cache on hit."""
    with _lock:
        cached = _store.get(session_id)
    if cached is not None:
        return cached

    pair = load_session_metadata(session_id)
    if pair is None:
        return None

    meta_a_json, meta_b_json = pair
    try:
        meta_a = VideoMeta.model_validate_json(meta_a_json)
        meta_b = VideoMeta.model_validate_json(meta_b_json)
    except Exception as e:  # noqa: BLE001 -- corrupt payload -> treat as miss
        log.warning("load_session_metadata(%s) returned unparseable JSON: %s", session_id, e)
        return None

    pair_dict = {"A": meta_a, "B": meta_b}
    with _lock:
        _store[session_id] = pair_dict
    log.info("Re-hydrated session %s from Qdrant", session_id)
    return pair_dict


def clear() -> None:
    """In-memory cache only. Qdrant points stay; use vector_store.delete_session
    if you actually want to wipe a session from durable storage."""
    with _lock:
        _store.clear()
