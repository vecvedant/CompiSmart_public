"""Day 1 smoke test: end-to-end YouTube ingest, no FastAPI involved.

Run from the backend/ directory with the venv active:
    python -m scripts.smoke_youtube https://www.youtube.com/watch?v=<id>

Tests:
    1. URL detection
    2. yt-dlp metadata extraction
    3. youtube-transcript-api caption fetch
    4. sentence-aware chunking
    5. BGE-small embedding (downloads model on first run, ~133MB)
    6. (optional) Qdrant upsert + search if QDRANT_URL is set in .env

Exits 0 on success, prints a clean summary table.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

# Make `app.*` imports work when run as `python -m scripts.smoke_youtube`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.ingest.chunking import chunk_transcript
from app.ingest.detect import detect_platform, extract_youtube_id
from app.ingest.youtube import ingest_youtube
from app.rag.embeddings import embed_query, embed_texts


def _section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def main(url: str, *, with_qdrant: bool) -> int:
    t0 = time.perf_counter()

    _section("1) URL detection")
    platform = detect_platform(url)
    yt_id = extract_youtube_id(url) if platform == "youtube" else "<n/a>"
    print(f"  platform : {platform}")
    print(f"  video_id : {yt_id}")
    if platform != "youtube":
        print("  smoke test only covers YouTube on Day 1; aborting")
        return 1

    _section("2) yt-dlp metadata + 3) transcript")
    t = time.perf_counter()
    meta, segments = ingest_youtube(url, slot="A")
    print(f"  fetched in {time.perf_counter() - t:.2f}s")
    print(f"  title          : {meta.title}")
    print(f"  creator        : {meta.creator}")
    print(f"  follower_count : {meta.follower_count}")
    print(f"  views          : {meta.views:,}")
    print(f"  likes          : {meta.likes:,}")
    print(f"  comments       : {meta.comments:,}")
    print(f"  engagement     : {meta.engagement_rate:.2f}%")
    print(f"  duration_sec   : {meta.duration_sec}")
    print(f"  upload_date    : {meta.upload_date}")
    print(f"  age_days       : {meta.age_days}")
    print(f"  view_velocity  : {meta.view_velocity:.0f}/day" if meta.view_velocity else "  view_velocity  : n/a")
    print(f"  life_stage     : {meta.life_stage}")
    print(f"  hashtags       : {meta.hashtags[:8]}")
    print(f"  segments       : {len(segments)} (first: {segments[0].text[:60]!r}...)")

    _section("4) chunking")
    t = time.perf_counter()
    chunks = chunk_transcript(segments, video_slot="A")
    print(f"  chunked in {time.perf_counter() - t:.2f}s -> {len(chunks)} chunks")
    if chunks:
        c0 = chunks[0]
        print(f"  chunk 0 ({c0.start_sec:.1f}-{c0.end_sec:.1f}s, {len(c0.text)} chars):")
        print(f"    {c0.text[:200]}{'...' if len(c0.text) > 200 else ''}")

    _section("5) BGE embedding")
    t = time.perf_counter()
    vecs = embed_texts([c.text for c in chunks])
    print(f"  embedded {len(vecs)} chunks in {time.perf_counter() - t:.2f}s "
          f"(dim={len(vecs[0]) if vecs else 0})")

    if not with_qdrant:
        print("\n  [skipping Qdrant -- pass --qdrant to run upsert/search]")
        print(f"\nTotal: {time.perf_counter() - t0:.2f}s. Day 1 paths verified OK")
        return 0

    _section("6) Qdrant upsert + search")
    if not settings.qdrant_url:
        print("  QDRANT_URL not set in .env -- skipping Qdrant test.")
        print("  Sign up at https://cloud.qdrant.io/ for a free 1 GB cluster.")
        return 0
    from app.rag.vector_store import search, upsert_chunks
    session_id = f"smoke-{uuid.uuid4().hex[:8]}"
    t = time.perf_counter()
    n = upsert_chunks(session_id, meta.video_id, chunks)
    print(f"  upserted {n} points in {time.perf_counter() - t:.2f}s (session={session_id})")
    t = time.perf_counter()
    qv = embed_query("what is this video about")
    hits = search(session_id, qv, video_slot="A", kind="transcript", limit=3)
    print(f"  searched in {time.perf_counter() - t:.2f}s -> {len(hits)} hits")
    for h in hits:
        print(f"    score={h['score']:.3f}  chunk_idx={h['chunk_idx']}  "
              f"text={h['text'][:80]!r}...")

    print(f"\nTotal: {time.perf_counter() - t0:.2f}s. Day 1 end-to-end OK")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="YouTube URL to ingest")
    parser.add_argument("--qdrant", action="store_true", help="Also test Qdrant upsert+search (needs QDRANT_URL)")
    args = parser.parse_args()
    sys.exit(main(args.url, with_qdrant=args.qdrant))
