"""End-to-end smoke test for the v2 stack.

Hits the live local backend and exercises each new endpoint:
  GET  /api/health
  GET  /api/niches
  GET  /api/feed/tech              (cold + warm)
  POST /api/assets                 (article from a feed URL)
  GET  /api/assets?session_id=...  (verify it shows up)
  POST /api/chat                   (asset-mode chat, SSE stream)
  POST /api/build                  (build a short blog_post, SSE stream)
  DELETE /api/assets/<id>          (cleanup)

Usage:
    python scripts/smoke_v2.py [--base http://localhost:8000]
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import uuid

import httpx

# Force UTF-8 on Windows consoles so emoji titles don't crash the print.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def banner(s: str) -> None:
    print(f"\n=== {s} ===")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()
    base = args.base.rstrip("/")
    session_id = "smoke-" + uuid.uuid4().hex[:8]

    with httpx.Client(base_url=base, timeout=args.timeout) as c:
        banner("health")
        r = c.get("/api/health")
        print(r.status_code, r.json())

        banner("niches")
        r = c.get("/api/niches")
        data = r.json()
        print(f"{r.status_code} -> {len(data.get('niches', []))} niches")
        print("first 3:", [n["label"] for n in data["niches"][:3]])

        banner("feed/tech (cold)")
        t = time.time()
        r = c.get("/api/feed/tech")
        d = r.json()
        print(f"{r.status_code} cached={d.get('cached')} count={d.get('count')} in {time.time()-t:.1f}s")
        if d.get("items"):
            for it in d["items"][:3]:
                print(f"  - [{it['type']}] {it['title'][:60]}")
        first_article = next((i for i in d.get("items", []) if i["type"] == "news"), None)

        banner("feed/tech (warm)")
        t = time.time()
        r = c.get("/api/feed/tech")
        d = r.json()
        print(f"{r.status_code} cached={d.get('cached')} in {time.time()-t:.2f}s")

        if not first_article:
            print("No news article in feed — skipping asset/chat tests")
            return 0

        banner("POST /api/assets")
        r = c.post("/api/assets", json={
            "session_id": session_id,
            "type": "article",
            "source_url": first_article["url"],
            "title": first_article["title"],
            "summary": first_article["summary"],
            "niche_slug": "tech",
        })
        print(r.status_code)
        asset = r.json()
        asset_id = asset["id"]
        print(f"created asset_id={asset_id} status={asset['ingest_status']}")

        banner("poll asset until ready (max 60s)")
        for i in range(20):
            time.sleep(3)
            r = c.get("/api/assets", params={"session_id": session_id})
            rows = r.json().get("assets", [])
            row = next((a for a in rows if a["id"] == asset_id), None)
            if row:
                print(f"  t={i*3}s status={row['ingest_status']}")
                if row["ingest_status"] in ("ready", "failed"):
                    asset = row
                    break

        if asset["ingest_status"] != "ready":
            print("Asset not ready — skipping chat/build")
            return 1

        banner("POST /api/chat (asset-mode, SSE)")
        with c.stream("POST", "/api/chat", json={
            "session_id": session_id,
            "message": "What is the key idea of this article in one sentence?",
        }) as s:
            tokens = []
            for line in s.iter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    try:
                        payload = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if "token" in payload:
                        tokens.append(payload["token"])
                    if payload.get("done") or "error" in payload:
                        break
        print("answer:", ("".join(tokens))[:300])

        banner("POST /api/build (short blog_post, SSE)")
        with c.stream("POST", "/api/build", json={
            "session_id": session_id,
            "asset_ids": [asset_id],
            "output_type": "blog_post",
            "tone": "confident",
            "length": "short",
        }) as s:
            outline = None
            draft = []
            for line in s.iter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    payload = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if "bullets" in payload:
                    outline = payload["bullets"]
                    print("outline:")
                    for b in outline:
                        print(f"  - {b}")
                if "token" in payload:
                    draft.append(payload["token"])
                if payload.get("draft_id"):
                    print("draft_id:", payload["draft_id"])
                    break
                if "error" in payload:
                    print("BUILD ERROR:", payload["error"])
                    break
        print("\ndraft preview:")
        print(("".join(draft))[:500])

        banner("DELETE /api/assets")
        r = c.delete(f"/api/assets/{asset_id}", params={"session_id": session_id})
        print(r.status_code, r.json())

    return 0


if __name__ == "__main__":
    sys.exit(main())
