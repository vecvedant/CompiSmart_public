"""drafts table: Build-mode generated/edited content."""
from __future__ import annotations

from typing import Optional

from app.db import execute, fetch_all, fetch_one, row_to_dict, rows_to_dicts


def _normalize(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    if row.get("id") is not None:
        row["id"] = str(row["id"])
    # asset_ids is uuid[]; convert to list[str].
    if row.get("asset_ids"):
        row["asset_ids"] = [str(a) for a in row["asset_ids"]]
    for ts in ("created_at", "updated_at"):
        if row.get(ts) is not None and hasattr(row[ts], "isoformat"):
            row[ts] = row[ts].isoformat()
    return row


async def upsert(draft: dict) -> dict:
    """Insert if no id, else update by id. Returns the saved row."""
    if draft.get("id"):
        row = await fetch_one(
            """
            update drafts
            set asset_ids   = coalesce($2::uuid[], asset_ids),
                output_type = coalesce($3, output_type),
                tone        = coalesce($4, tone),
                length      = coalesce($5, length),
                title       = coalesce($6, title),
                content_md  = coalesce($7, content_md),
                updated_at  = now()
            where id = $1 and session_id = $8
            returning *
            """,
            draft["id"],
            draft.get("asset_ids"),
            draft.get("output_type"),
            draft.get("tone"),
            draft.get("length"),
            draft.get("title"),
            draft.get("content_md"),
            draft["session_id"],
        )
    else:
        row = await fetch_one(
            """
            insert into drafts (session_id, asset_ids, output_type, tone, length, title, content_md)
            values ($1, $2::uuid[], $3, $4, $5, $6, $7)
            returning *
            """,
            draft["session_id"],
            draft.get("asset_ids") or [],
            draft.get("output_type") or "blog_post",
            draft.get("tone") or "confident",
            draft.get("length") or "medium",
            draft.get("title") or "",
            draft.get("content_md") or "",
        )
    return _normalize(row_to_dict(row)) or {}


async def get(draft_id: str, session_id: str) -> Optional[dict]:
    row = await fetch_one(
        "select * from drafts where id = $1 and session_id = $2",
        draft_id, session_id,
    )
    return _normalize(row_to_dict(row))


async def list_for_session(session_id: str) -> list[dict]:
    rows = await fetch_all(
        "select * from drafts where session_id = $1 order by created_at desc",
        session_id,
    )
    return [_normalize(r) or r for r in rows_to_dicts(rows)]
