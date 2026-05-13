"""artifacts table: Claude-Code-style outputs spawned from chat intent."""
from __future__ import annotations

import json
from typing import Optional

from app.db import execute, fetch_all, fetch_one, row_to_dict, rows_to_dicts


def _normalize(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    if row.get("id") is not None:
        row["id"] = str(row["id"])
    if row.get("asset_ids"):
        row["asset_ids"] = [str(a) for a in row["asset_ids"]]
    if isinstance(row.get("payload_json"), str):
        try:
            row["payload_json"] = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            row["payload_json"] = {}
    for ts in ("created_at", "updated_at"):
        if row.get(ts) is not None and hasattr(row[ts], "isoformat"):
            row[ts] = row[ts].isoformat()
    return row


async def insert(artifact: dict) -> dict:
    row = await fetch_one(
        """
        insert into artifacts (session_id, kind, title, status, asset_ids, prompt, payload_json)
        values ($1, $2, $3, $4, $5::uuid[], $6, $7::jsonb)
        returning *
        """,
        artifact["session_id"],
        artifact["kind"],
        artifact.get("title") or "",
        artifact.get("status") or "pending",
        artifact.get("asset_ids") or [],
        artifact.get("prompt") or "",
        json.dumps(artifact.get("payload_json") or {}),
    )
    return _normalize(row_to_dict(row)) or {}


async def update_payload(artifact_id: str, payload: dict, *, status: Optional[str] = None, title: Optional[str] = None) -> None:
    sets = ["payload_json = $2::jsonb", "updated_at = now()"]
    args: list = [artifact_id, json.dumps(payload)]
    if status is not None:
        sets.append(f"status = ${len(args) + 1}")
        args.append(status)
    if title is not None:
        sets.append(f"title = ${len(args) + 1}")
        args.append(title)
    await execute(
        f"update artifacts set {', '.join(sets)} where id = $1",
        *args,
    )


async def set_status(artifact_id: str, status: str) -> None:
    await execute(
        "update artifacts set status = $2, updated_at = now() where id = $1",
        artifact_id, status,
    )


async def get(artifact_id: str, session_id: str) -> Optional[dict]:
    row = await fetch_one(
        "select * from artifacts where id = $1 and session_id = $2",
        artifact_id, session_id,
    )
    return _normalize(row_to_dict(row))


async def list_for_session(session_id: str, limit: int = 50) -> list[dict]:
    rows = await fetch_all(
        "select * from artifacts where session_id = $1 order by created_at desc limit $2",
        session_id, limit,
    )
    return [_normalize(r) or r for r in rows_to_dicts(rows)]


async def delete(artifact_id: str, session_id: str) -> None:
    await execute(
        "delete from artifacts where id = $1 and session_id = $2",
        artifact_id, session_id,
    )
