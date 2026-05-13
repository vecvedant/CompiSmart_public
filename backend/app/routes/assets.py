"""Asset CRUD: list / add / delete saved items for a session.

Add semantics: writes the Supabase row immediately with ingest_status=pending,
fires processing in the background, returns the row to the frontend so the
sidebar can show a "processing..." chip. Frontend re-fetches (or polls) to
see status flip to "ready"/"failed".
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app import supabase_client
from app.assets.processor import process_asset
from app.models import AddAssetRequest
from app.rag.vector_store import delete_asset as qdrant_delete_asset

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/assets")
async def list_assets(session_id: str = Query(...)) -> dict:
    if not supabase_client.is_configured():
        raise HTTPException(503, "Supabase not configured")
    rows = await supabase_client.list_assets(session_id)
    return {"session_id": session_id, "count": len(rows), "assets": rows}


@router.post("/assets")
async def add_asset(req: AddAssetRequest) -> dict:
    if not supabase_client.is_configured():
        raise HTTPException(503, "Supabase not configured")
    if req.type in ("article", "video") and not req.source_url:
        raise HTTPException(400, "source_url required for article/video assets")

    row = {
        "session_id": req.session_id,
        "type": req.type,
        "source_url": req.source_url,
        "title": req.title or req.source_url or "Untitled",
        "summary": req.summary or "",
        "niche_slug": req.niche_slug,
        "metadata_json": req.metadata or {},
        "ingest_status": "pending",
    }
    inserted = await supabase_client.insert_asset(row)
    log.info("Asset created id=%s type=%s session=%s", inserted.get("id"), req.type, req.session_id)

    # Fire processing in the background so the API call returns instantly.
    asyncio.create_task(process_asset(inserted))

    return inserted


@router.delete("/assets/{asset_id}")
async def remove_asset(asset_id: str, session_id: str = Query(...)) -> dict:
    if not supabase_client.is_configured():
        raise HTTPException(503, "Supabase not configured")
    await supabase_client.delete_asset(asset_id, session_id)
    # Best-effort Qdrant cleanup; failure here doesn't roll back the Supabase delete.
    try:
        await asyncio.to_thread(qdrant_delete_asset, asset_id)
    except Exception as e:
        log.warning("Qdrant delete_asset(%s) failed: %s", asset_id, e)
    return {"ok": True, "asset_id": asset_id}
