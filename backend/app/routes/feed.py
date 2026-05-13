"""GET /api/feed/:niche, POST /api/feed/:niche/refresh."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app import niches as niches_mod
from app.feed.aggregator import get_feed

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/feed/{niche_slug}")
async def get_niche_feed(niche_slug: str) -> dict:
    niche = niches_mod.get(niche_slug)
    if not niche:
        raise HTTPException(404, f"unknown niche: {niche_slug}")
    items, cached = await get_feed(niche, force_refresh=False)
    return {
        "niche": niche.slug,
        "cached": cached,
        "count": len(items),
        "items": [i.model_dump(mode="json") for i in items],
    }


@router.post("/feed/{niche_slug}/refresh")
async def refresh_niche_feed(niche_slug: str) -> dict:
    niche = niches_mod.get(niche_slug)
    if not niche:
        raise HTTPException(404, f"unknown niche: {niche_slug}")
    items, _ = await get_feed(niche, force_refresh=True)
    return {
        "niche": niche.slug,
        "cached": False,
        "count": len(items),
        "items": [i.model_dump(mode="json") for i in items],
    }
