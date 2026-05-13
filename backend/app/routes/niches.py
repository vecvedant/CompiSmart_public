"""GET /api/niches — static taxonomy for the niche picker page."""
from __future__ import annotations

from fastapi import APIRouter

from app.niches import NICHES

router = APIRouter()


@router.get("/niches")
async def list_niches() -> dict:
    return {
        "niches": [
            {
                "slug": n.slug,
                "label": n.label,
                "description": n.description,
                "icon": n.icon,
            }
            for n in NICHES
        ]
    }
