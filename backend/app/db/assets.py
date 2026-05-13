"""assets table: per-session saved items (article / video / note / compare)."""
from __future__ import annotations

import json
from typing import Optional

from app.db import execute, fetch_all, fetch_one, row_to_dict, rows_to_dicts


def _normalize(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    # asyncpg returns uuid columns as UUID objects; we want plain strings
    # everywhere downstream (qdrant MatchAny + JSON responses).
    if row.get("id") is not None:
        row["id"] = str(row["id"])
    if isinstance(row.get("metadata_json"), str):
        try:
            row["metadata_json"] = json.loads(row["metadata_json"])
        except json.JSONDecodeError:
            row["metadata_json"] = {}
    if row.get("added_at") is not None:
        row["added_at"] = row["added_at"].isoformat() if hasattr(row["added_at"], "isoformat") else str(row["added_at"])
    return row


async def insert(asset: dict) -> dict:
    """Insert a new asset; returns the inserted row (with generated id + added_at).

    canonical_url is computed from source_url so cross-session URL cache
    lookups work — see app/db/url_cache.py.
    """
    # Lazy import to avoid circular (url_cache imports from db package).
    from app.db.url_cache import canonical_url as canonicalize
    src = asset.get("source_url")
    canonical = canonicalize(src) if src else None
    row = await fetch_one(
        """
        insert into assets
            (session_id, type, source_url, canonical_url, title, summary, body_text,
             metadata_json, niche_slug, ingest_status)
        values ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)
        returning *
        """,
        asset["session_id"],
        asset["type"],
        src,
        canonical,
        asset.get("title") or src or "Untitled",
        asset.get("summary") or "",
        asset.get("body_text"),
        json.dumps(asset.get("metadata_json") or {}),
        asset.get("niche_slug"),
        asset.get("ingest_status") or "pending",
    )
    return _normalize(row_to_dict(row)) or {}


async def update(asset_id: str, patch: dict) -> None:
    """Set arbitrary columns on one asset. Whitelist of fields we allow."""
    allowed = {"title", "summary", "body_text", "metadata_json", "ingest_status", "niche_slug"}
    cols = [k for k in patch.keys() if k in allowed]
    if not cols:
        return
    sets = []
    values: list = []
    for i, col in enumerate(cols, start=1):
        v = patch[col]
        if col == "metadata_json":
            sets.append(f"{col} = ${i}::jsonb")
            values.append(json.dumps(v))
        else:
            sets.append(f"{col} = ${i}")
            values.append(v)
    values.append(asset_id)
    await execute(
        f"update assets set {', '.join(sets)} where id = ${len(values)}",
        *values,
    )


async def get(asset_id: str) -> Optional[dict]:
    row = await fetch_one("select * from assets where id = $1", asset_id)
    return _normalize(row_to_dict(row))


async def list_for_session(session_id: str) -> list[dict]:
    rows = await fetch_all(
        "select * from assets where session_id = $1 order by added_at desc",
        session_id,
    )
    return [_normalize(r) or r for r in rows_to_dicts(rows)]


async def delete(asset_id: str, session_id: str) -> None:
    """Session-scoped delete: refuses to remove if the session doesn't own it."""
    await execute(
        "delete from assets where id = $1 and session_id = $2",
        asset_id, session_id,
    )
