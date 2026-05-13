"""Time the compare flow with streaming verdict."""
from __future__ import annotations

import asyncio, io, json, os, sys, time, uuid
from pathlib import Path
import asyncpg, httpx

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
for line in (Path(__file__).resolve().parents[2] / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ[k] = v


async def seed_two_videos() -> str:
    sid = "cmp-" + uuid.uuid4().hex[:6]
    conn = await asyncpg.connect(dsn=os.environ["SUPABASE_URL"], statement_cache_size=0)
    rows = await conn.fetch(
        "select type, source_url, canonical_url, title, summary, body_text, "
        "metadata_json, niche_slug from assets "
        "where ingest_status='ready' and type='video' order by added_at desc limit 2"
    )
    for r in rows:
        await conn.execute(
            "insert into assets (session_id, type, source_url, canonical_url, title, "
            "summary, body_text, metadata_json, niche_slug, ingest_status) "
            "values ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,'ready')",
            sid, r["type"], r["source_url"], r["canonical_url"], r["title"],
            r["summary"], r["body_text"], r["metadata_json"], r["niche_slug"],
        )
    await conn.close()
    return sid


async def main():
    sid = await seed_two_videos()
    print(f"fresh session: {sid} (2 ready videos)")
    t0 = time.time()
    first_token = None
    done_at = None
    token_count = 0
    preview = []
    with httpx.Client(timeout=180) as c:
        with c.stream("POST", "http://127.0.0.1:8000/api/chat",
                      json={"session_id": sid, "message": "compare them"}) as s:
            cur = None
            for line in s.iter_lines():
                if line.startswith("event:"): cur = line[6:].strip()
                elif line.startswith("data:"):
                    try: d = json.loads(line[5:].strip())
                    except: continue
                    if cur == "artifact_token" and d.get("field") == "streaming_preview":
                        if first_token is None:
                            first_token = time.time() - t0
                        token_count += 1
                        preview.append(d.get("text",""))
                    if cur == "artifact_done":
                        done_at = time.time() - t0
                    if cur == "done":
                        break
    print()
    print(f"first streaming token: {first_token:.2f}s" if first_token else "no streaming tokens")
    print(f"total time:            {done_at:.2f}s" if done_at else "no artifact_done")
    print(f"streaming chunks:      {token_count}")
    if preview:
        print(f"preview start:         {''.join(preview)[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
