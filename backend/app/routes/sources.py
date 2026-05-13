"""GET /api/sessions/:id/sources -- payload for the Sources & Signals panel.

Returns two parallel structures per video:
  - internal: what we know from the video itself (hook, top transcript
    chunks, top comments, headline metrics)
  - external: web pages Gemini cited via Search grounding while answering
    chat questions in this session

The internal data is read from the session store + Qdrant on every call,
so refreshing the panel after each chat turn keeps it consistent. The
external list grows as Gemini grounds more answers; it lives in
`app.rag.web_sources` (in-memory, per session).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import sessions
from app.rag.vector_store import list_chunks
from app.rag.web_sources import get_web_sources

router = APIRouter()

# Number of items each section shows. Kept small so the sidebar stays
# scannable; the chat itself surfaces deeper retrieval per question.
TOP_TRANSCRIPT = 3
TOP_COMMENTS = 3


def _internal_for(session_id: str, slot: str, meta) -> dict:
    transcript_chunks = list_chunks(
        session_id, video_slot=slot, kind="transcript", limit=50
    )
    # chunk_idx 0 is the hook -- the opening words. Used by the
    # frontend to highlight a "Hook" row above the rest.
    hook = transcript_chunks[0] if transcript_chunks else None

    # Top transcript bits = first N by chunk_idx (already sorted by
    # list_chunks). For the hook, we drop the first chunk so we don't
    # duplicate it in the "Top transcript" list right below — but only
    # when there are enough chunks to spare; otherwise we show everything
    # we have, hook included, so the panel isn't blank for short videos.
    if len(transcript_chunks) > TOP_TRANSCRIPT + 1:
        top_transcript = transcript_chunks[1 : 1 + TOP_TRANSCRIPT]
    else:
        top_transcript = transcript_chunks[: TOP_TRANSCRIPT]

    # Top comments come pre-ranked from ingest -- meta.top_comments is
    # ordered by likes desc (see ingest/comments.py). We just slice.
    top_comments = [c.model_dump() for c in (meta.top_comments or [])[:TOP_COMMENTS]]

    return {
        "hook": (
            {
                "text": hook.get("text", ""),
                "start_sec": hook.get("start_sec"),
                "end_sec": hook.get("end_sec"),
                "chunk_idx": hook.get("chunk_idx", 0),
            }
            if hook
            else None
        ),
        "top_transcript": [
            {
                "text": c.get("text", ""),
                "start_sec": c.get("start_sec"),
                "end_sec": c.get("end_sec"),
                "chunk_idx": c.get("chunk_idx"),
            }
            for c in top_transcript
        ],
        "top_comments": top_comments,
        "metrics": {
            "views": meta.views,
            "likes": meta.likes,
            "comments": meta.comments,
            "engagement_rate": meta.engagement_rate,
            "follower_count": meta.follower_count,
            "view_velocity": meta.view_velocity,
            "life_stage": meta.life_stage,
        },
    }


@router.get("/sessions/{session_id}/sources")
async def get_sources(session_id: str) -> dict:
    found = sessions.get(session_id)
    if not found:
        raise HTTPException(status_code=404, detail="session not found")

    return {
        "A": _internal_for(session_id, "A", found["A"]),
        "B": _internal_for(session_id, "B", found["B"]),
        # External web sources are not per-video. Gemini grounds against the
        # full conversation, not a single video, so we return one shared list.
        "external": [s.model_dump() for s in get_web_sources(session_id)],
    }
