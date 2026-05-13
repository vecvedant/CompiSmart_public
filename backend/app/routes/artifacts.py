"""Artifact CRUD: list, fetch one, delete, save-as-asset."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app import supabase_client
from app.assets.processor import process_asset
from app.db import artifacts as art_db
from app.db import is_configured as db_is_configured

log = logging.getLogger(__name__)
router = APIRouter()


class SaveAsAssetRequest(BaseModel):
    session_id: str


@router.get("/artifacts")
async def list_artifacts(session_id: str = Query(...)) -> dict:
    if not db_is_configured():
        raise HTTPException(503, "Database not configured")
    rows = await art_db.list_for_session(session_id)
    return {"session_id": session_id, "count": len(rows), "artifacts": rows}


@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str, session_id: str = Query(...)) -> dict:
    if not db_is_configured():
        raise HTTPException(503, "Database not configured")
    row = await art_db.get(artifact_id, session_id)
    if not row:
        raise HTTPException(404, "Artifact not found")
    return row


@router.delete("/artifacts/{artifact_id}")
async def delete_artifact(artifact_id: str, session_id: str = Query(...)) -> dict:
    if not db_is_configured():
        raise HTTPException(503, "Database not configured")
    await art_db.delete(artifact_id, session_id)
    return {"ok": True, "id": artifact_id}


@router.post("/artifacts/{artifact_id}/save-as-asset")
async def save_artifact_as_asset(artifact_id: str, req: SaveAsAssetRequest) -> dict:
    """Convert an artifact's content into a note-type asset so future chats
    can reference it. Useful for: drafted blog post -> save as asset -> ask
    "rewrite this in a different tone".
    """
    if not db_is_configured():
        raise HTTPException(503, "Database not configured")
    art = await art_db.get(artifact_id, req.session_id)
    if not art:
        raise HTTPException(404, "Artifact not found")
    if art["status"] != "ready":
        raise HTTPException(409, f"Artifact is {art['status']}, not ready")

    p = art.get("payload_json") or {}
    body = _extract_body_from_payload(art["kind"], p)
    if not body:
        raise HTTPException(400, "Artifact has no extractable body content")

    title = art.get("title") or f"{art['kind']} from chat"

    row = {
        "session_id": req.session_id,
        "type": "note",
        "title": title[:300],
        "summary": body[:280],
        "body_text": body[:50000],
        "metadata_json": {
            "from_artifact_id": artifact_id,
            "from_artifact_kind": art["kind"],
        },
        "ingest_status": "pending",
    }
    inserted = await supabase_client.insert_asset(row)
    log.info("save-as-asset: artifact=%s -> asset=%s", artifact_id, inserted.get("id"))

    # Process in the background so the asset becomes chat-queryable.
    asyncio.create_task(process_asset(inserted))
    return inserted


def _extract_body_from_payload(kind: str, p: dict) -> str:
    if kind == "draft":
        return str(p.get("content_md") or "").strip()
    if kind == "summary":
        bits = []
        if p.get("headline"):
            bits.append(p["headline"])
        for b in (p.get("bullets") or []):
            bits.append(f"- {b}")
        if p.get("takeaway"):
            bits.append("")
            bits.append(p["takeaway"])
        return "\n".join(bits).strip()
    if kind == "compare":
        v = p.get("verdict") or {}
        bits = []
        if v.get("opinion"):
            bits.append(v["opinion"])
        for r in (v.get("reasons") or []):
            bits.append(f"- {r}")
        return "\n".join(bits).strip()
    if kind == "quotes":
        quotes = (p.get("quotes") or [])
        return "\n\n".join(
            f'"{q.get("text","")}" ({q.get("source","")})' for q in quotes
        ).strip()
    if kind == "metrics":
        return ""  # Not useful as a note asset.
    return ""
