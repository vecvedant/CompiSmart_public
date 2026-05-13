"""Simulate the real MCQ user flow (chained clarifications) to verify the
context-aware dispatcher no longer loops on minimal answer phrases.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import uuid
from pathlib import Path

import asyncpg
import httpx

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

for line in (Path(__file__).resolve().parents[2] / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k] = v


async def seed_fresh_session() -> str:
    """Clone one ready asset into a brand-new session_id so we test a clean
    chat-message history.
    """
    sid = "mcq-" + uuid.uuid4().hex[:6]
    conn = await asyncpg.connect(dsn=os.environ["SUPABASE_URL"], statement_cache_size=0)
    src = await conn.fetchrow(
        "select type, source_url, canonical_url, title, summary, body_text, "
        "metadata_json, niche_slug from assets "
        "where ingest_status = 'ready' order by added_at desc limit 1"
    )
    await conn.execute(
        "insert into assets (session_id, type, source_url, canonical_url, "
        "title, summary, body_text, metadata_json, niche_slug, ingest_status) "
        "values ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, 'ready')",
        sid,
        src["type"], src["source_url"], src["canonical_url"],
        src["title"], src["summary"], src["body_text"],
        src["metadata_json"], src["niche_slug"],
    )
    await conn.close()
    return sid


def chat_first_relevant(sid: str, message: str) -> tuple[str, str]:
    """Stream the chat until a clarification, artifact_done, or done event."""
    with httpx.Client(timeout=240) as c:
        with c.stream(
            "POST", "http://127.0.0.1:8000/api/chat",
            json={"session_id": sid, "message": message},
        ) as s:
            cur = None
            for line in s.iter_lines():
                if line.startswith("event:"):
                    cur = line[6:].strip()
                elif line.startswith("data:"):
                    try:
                        d = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if cur == "clarification":
                        return ("clar", d.get("question", ""))
                    if cur == "artifact_done":
                        md = (d.get("payload") or {}).get("content_md", "")
                        return ("done", md[:120])
                    if cur == "done":
                        return ("done", "")
    return ("?", "")


async def main() -> None:
    sid = await seed_fresh_session()
    print(f"fresh session: {sid}\n")

    print('user: "draft something from these"')
    r = chat_first_relevant(sid, "draft something from these")
    print(f"  bot: {r}\n")

    print('user clicks [Blog post] → frontend sends: "write a Blog post"')
    r = chat_first_relevant(sid, "write a Blog post")
    print(f"  bot: {r}\n")

    print('user clicks [Confident] → frontend sends: "write a Confident"')
    print("  (this is the case that used to loop forever)")
    r = chat_first_relevant(sid, "write a Confident")
    print(f"  bot: {r}\n")

    if r[0] == "done":
        print("  ✓ FIXED — bot generated the draft instead of looping")
    elif r[0] == "clar" and "tone" in r[1].lower():
        print("  partial: still asking tone (already answered)")
    elif r[0] == "clar" and "kind" in r[1].lower():
        print("  ✗ STILL LOOPING — asked output type again")
    else:
        print(f"  unexpected: {r}")


if __name__ == "__main__":
    asyncio.run(main())
