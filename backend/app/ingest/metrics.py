"""Pure functions for computed video metrics. Shared across platforms."""

from __future__ import annotations

from app.models import LifeStage


def engagement_rate(views: int, likes: int, comments: int) -> float:
    """(likes + comments) / views × 100. Guards against zero-views."""
    if views <= 0:
        return 0.0
    return (likes + comments) / views * 100.0


def life_stage(age_days: int | None) -> LifeStage | None:
    """Heuristic — NOT a measurement. State openly in the UI."""
    if age_days is None:
        return None
    if age_days <= 3:
        return "fresh"
    if age_days <= 14:
        return "early"
    if age_days <= 90:
        return "mature"
    return "saturated"
