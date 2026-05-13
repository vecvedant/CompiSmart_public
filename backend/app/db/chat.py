"""chat_messages table: persistent per-session chat history."""
from __future__ import annotations

import json

from app.db import execute, fetch_all, fetch_one, rows_to_dicts


async def next_turn_idx(session_id: str) -> int:
    row = await fetch_one(
        "select coalesce(max(turn_idx) + 1, 0) as next from chat_messages where session_id = $1",
        session_id,
    )
    return int(row["next"]) if row else 0


async def insert(session_id: str, turn_idx: int, role: str, content: str, metadata: dict | None = None) -> None:
    await execute(
        """
        insert into chat_messages (session_id, turn_idx, role, content, metadata)
        values ($1, $2, $3, $4, $5::jsonb)
        on conflict (session_id, turn_idx) do nothing
        """,
        session_id, turn_idx, role, content, json.dumps(metadata or {}),
    )


async def list_for_session(session_id: str) -> list[dict]:
    rows = await fetch_all(
        "select * from chat_messages where session_id = $1 order by turn_idx",
        session_id,
    )
    out = rows_to_dicts(rows)
    for r in out:
        if isinstance(r.get("metadata"), str):
            try:
                r["metadata"] = json.loads(r["metadata"])
            except json.JSONDecodeError:
                r["metadata"] = {}
    return out


async def clear(session_id: str) -> None:
    await execute("delete from chat_messages where session_id = $1", session_id)
