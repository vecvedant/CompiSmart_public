"""Smoke test for the multi-step clarification + drafts persistence flow."""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from pathlib import Path

import asyncpg
import httpx

# Force UTF-8 on Windows console.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Load .env
for line in (Path(__file__).resolve().parents[2] / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k] = v


async def latest_session_with_assets() -> tuple[str, int, int]:
    conn = await asyncpg.connect(dsn=os.environ["SUPABASE_URL"], statement_cache_size=0)
    row = await conn.fetchrow(
        "select session_id, count(*) as n from assets "
        "where ingest_status = 'ready' "
        "group by session_id order by max(added_at) desc limit 1"
    )
    drafts_before = await conn.fetchval(
        "select count(*) from drafts where session_id = $1", row["session_id"]
    )
    await conn.close()
    return row["session_id"], int(row["n"]), int(drafts_before)


async def count_drafts(sid: str) -> int:
    conn = await asyncpg.connect(dsn=os.environ["SUPABASE_URL"], statement_cache_size=0)
    n = await conn.fetchval("select count(*) from drafts where session_id = $1", sid)
    await conn.close()
    return int(n)


def chat(sid: str, message: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    with httpx.Client(timeout=240) as c:
        with c.stream("POST", "http://127.0.0.1:8000/api/chat",
                      json={"session_id": sid, "message": message}) as s:
            cur = None
            for line in s.iter_lines():
                if line.startswith("event:"):
                    cur = line[6:].strip()
                elif line.startswith("data:"):
                    try:
                        data = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    events.append((cur or "data", data))
                    if cur == "done":
                        return events
    return events


async def main() -> None:
    sid, n_assets, drafts_before = await latest_session_with_assets()
    print(f"session: {sid} ({n_assets} ready assets, {drafts_before} drafts before)\n")

    print("=== STEP 1: draft something (expects output_type MCQ) ===")
    for ev, d in chat(sid, "draft something from these"):
        if ev == "clarification":
            print(f"  ✓ MCQ: {d['question']}")
            print(f"    options: {[o['label'] for o in d.get('options', [])]}")
            break
    print()

    print("=== STEP 2: write a blog post (expects tone MCQ now) ===")
    for ev, d in chat(sid, "write a blog post"):
        if ev == "clarification":
            print(f"  ✓ MCQ: {d['question']}")
            print(f"    options: {[o['label'] for o in d.get('options', [])]}")
            break
    print()

    print("=== STEP 3: write a confident blog post (no clarification, generates) ===")
    hit_clar = False
    got_done = False
    md = ""
    draft_id = None
    for ev, d in chat(sid, "write a confident blog post from these"):
        if ev == "clarification":
            hit_clar = True
        if ev == "artifact_done":
            got_done = True
            pl = d.get("payload") or {}
            md = pl.get("content_md") or ""
            draft_id = pl.get("draft_id")
    em = md.count("—") + md.count("–")
    print(f"  clarification fired: {hit_clar}")
    print(f"  artifact_done received: {got_done}")
    print(f"  draft length: {len(md)} chars")
    print(f"  em-dashes in output: {em}")
    print(f"  draft_id in payload: {draft_id!r}")
    print(f"  preview: {md[:200]!r}")

    drafts_after = await count_drafts(sid)
    print()
    print(f"drafts table delta: {drafts_before} -> {drafts_after}")


if __name__ == "__main__":
    asyncio.run(main())
