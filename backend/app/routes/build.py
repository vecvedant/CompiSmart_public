"""POST /api/build  — SSE stream of the Build/Write pipeline.

Events emitted as SSE frames:
  event: outline       data: {"bullets": [...]}
  event: expand        data: {"section_count": N}
  data: {"token": "..."}     (many)
  event: done          data: {"draft_id": "..."}
  event: error         data: {"error": "..."}

Final draft is persisted to the `drafts` table once the polish stream completes.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app import supabase_client
from app.artifacts.generators import _strip_em_dashes
from app.build.writer import run_build
from app.models import BuildRequest, UpdateDraftRequest

log = logging.getLogger(__name__)
router = APIRouter()


def _sse(data: dict, event: str | None = None) -> str:
    out = []
    if event:
        out.append(f"event: {event}")
    out.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    out.append("")
    return "\n".join(out) + "\n"


@router.post("/build")
async def build(req: BuildRequest):
    if not supabase_client.is_configured():
        raise HTTPException(503, "Supabase not configured")
    if not req.asset_ids:
        raise HTTPException(400, "asset_ids must not be empty")

    all_assets = await supabase_client.list_assets(req.session_id)
    asset_map = {a["id"]: a for a in all_assets}
    selected = [asset_map[aid] for aid in req.asset_ids if aid in asset_map]
    # Only feed ready assets — pending/failed have no chunks yet.
    selected = [a for a in selected if a.get("ingest_status") == "ready"]
    if not selected:
        raise HTTPException(400, "no ready assets matched the given asset_ids")

    async def stream():
        polish_buf: list[str] = []
        try:
            async for event in run_build(req, selected):
                stage = event.get("stage")
                if stage == "outline":
                    yield _sse({"bullets": event["bullets"]}, event="outline")
                elif stage == "expand":
                    yield _sse({"section_count": event["section_count"]}, event="expand")
                elif stage == "polish_token":
                    polish_buf.append(event["text"])
                    yield _sse({"token": event["text"]})
                elif stage == "done":
                    full = _strip_em_dashes("".join(polish_buf).strip())
                    try:
                        saved = await supabase_client.upsert_draft({
                            "session_id": req.session_id,
                            "asset_ids": req.asset_ids,
                            "output_type": req.output_type,
                            "tone": req.tone,
                            "length": req.length,
                            "content_md": full,
                            "title": _title_from(full),
                        })
                        yield _sse({"draft_id": saved.get("id")}, event="done")
                    except Exception as e:
                        log.exception("draft save failed: %s", e)
                        yield _sse({"error": f"draft save failed: {e}"}, event="error")
        except Exception as e:
            log.exception("build stream failed: %s", e)
            yield _sse({"error": str(e)}, event="error")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _title_from(md: str) -> str:
    """Pick a title: first H1, else first non-empty line, capped."""
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()[:200]
    for line in md.splitlines():
        s = line.strip()
        if s:
            return s[:200]
    return "Untitled draft"
