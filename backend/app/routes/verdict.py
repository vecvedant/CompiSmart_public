"""GET /api/sessions/:id/verdict -- one-shot grounded summary.

Lazily generates and caches a Verdict per session. Pass ?refresh=1 to
force a regeneration (e.g. if the user wants a fresh take after a chat).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from app.models import Verdict
from app.rag.verdict import build_verdict

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/sessions/{session_id}/verdict")
async def get_verdict(
    session_id: str,
    refresh: bool = Query(False, description="Force-regenerate the verdict"),
) -> Verdict:
    try:
        return await build_verdict(session_id, force=refresh)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        log.exception("verdict generation failed for %s: %s", session_id, e)
        raise HTTPException(
            status_code=502,
            detail=f"verdict generation failed: {e}",
        ) from e
