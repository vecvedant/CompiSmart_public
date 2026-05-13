"""GET /api/sessions/:id — fetch the cards data for an ingested session."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import sessions
from app.models import VideoMeta

router = APIRouter()


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, VideoMeta]:
    found = sessions.get(session_id)
    if not found:
        raise HTTPException(status_code=404, detail="session not found")
    return found
