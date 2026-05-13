"""Smoke test the new YouTube pipeline (Data API metadata + pintostudio transcript)
by adding a YouTube video as an asset locally and watching it move through
the processor.
"""
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


async def clear_url_cache(canonical: str) -> None:
    """Delete any cached asset for this canonical URL so we test the cold path."""
    conn = await asyncpg.connect(dsn=os.environ["SUPABASE_URL"], statement_cache_size=0)
    n = await conn.fetchval(
        "select count(*) from assets where canonical_url = $1", canonical
    )
    if n:
        await conn.execute("delete from assets where canonical_url = $1", canonical)
        print(f"cleared {n} cached asset rows for {canonical}")
    await conn.close()


def main():
    test_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # "Me at the zoo"
    canonical = "youtube:jNQXAC9IVRw"
    asyncio.run(clear_url_cache(canonical))

    sid = "yt-smoke-" + uuid.uuid4().hex[:6]
    t0 = time.time()
    a = httpx.post("http://127.0.0.1:8000/api/assets", json={
        "session_id": sid, "type": "video", "source_url": test_url,
        "title": "Me at the zoo (test)", "summary": "First YouTube video ever",
        "niche_slug": "tech",
    }, timeout=30).json()
    aid = a["id"]
    print(f"asset created: {aid}")
    print(f"polling status...")
    final = None
    for i in range(45):
        time.sleep(2)
        r = httpx.get("http://127.0.0.1:8000/api/assets",
                      params={"session_id": sid}, timeout=10).json()
        row = next((x for x in r["assets"] if x["id"] == aid), None)
        if row and row["ingest_status"] in ("ready", "failed"):
            final = row
            break
    elapsed = time.time() - t0
    if not final:
        print(f"TIMEOUT after {elapsed:.0f}s, status remained pending")
        return
    print(f"final status: {final['ingest_status']} in {elapsed:.1f}s")
    meta = final.get("metadata_json") or {}
    print(f"  title:    {final.get('title', '')[:60]}")
    print(f"  creator:  {meta.get('creator')}")
    print(f"  views:    {meta.get('views', 0):,}")
    print(f"  body_len: {len(final.get('body_text') or '')} chars")
    if final["ingest_status"] == "failed":
        print(f"  ERROR:    {meta.get('error', '?')}")


if __name__ == "__main__":
    main()
