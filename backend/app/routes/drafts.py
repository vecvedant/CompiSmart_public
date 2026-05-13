"""Draft CRUD: list, fetch one, update content (post-edit)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app import supabase_client
from app.models import UpdateDraftRequest

router = APIRouter()


@router.get("/drafts")
async def list_drafts(session_id: str = Query(...)) -> dict:
    if not supabase_client.is_configured():
        raise HTTPException(503, "Supabase not configured")
    rows = await supabase_client.list_drafts(session_id)
    return {"session_id": session_id, "count": len(rows), "drafts": rows}


@router.get("/drafts/{draft_id}")
async def get_draft(draft_id: str, session_id: str = Query(...)) -> dict:
    if not supabase_client.is_configured():
        raise HTTPException(503, "Supabase not configured")
    rows = await supabase_client.list_drafts(session_id)
    for r in rows:
        if r["id"] == draft_id:
            return r
    raise HTTPException(404, "draft not found")


@router.put("/drafts/{draft_id}")
async def update_draft(draft_id: str, req: UpdateDraftRequest) -> dict:
    if not supabase_client.is_configured():
        raise HTTPException(503, "Supabase not configured")
    patch = {"id": draft_id, "session_id": req.session_id}
    if req.title is not None:
        patch["title"] = req.title
    if req.content_md is not None:
        patch["content_md"] = req.content_md
    patch["updated_at"] = "now()"
    saved = await supabase_client.upsert_draft(patch)
    return saved
