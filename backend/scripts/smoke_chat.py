"""Day 3 smoke test: end-to-end RAG chat against an existing ingested session.

Prereqs: an ingest must have already populated Qdrant + the in-memory
session store. Since the session store is per-process, this script ingests
two videos itself, then runs a chat query against the result -- everything
in one Python process.

Run from backend/ with the venv active and the 5 API keys in .env:

    python -m scripts.smoke_chat

Tests:
    1. Ingest two URLs (one YT short, one IG reel)
    2. Build chat chain for the new session
    3. Stream a chat answer; print tokens as they arrive
    4. Ask a follow-up to verify memory works
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import sessions
from app.ingest.chunking import chunk_transcript
from app.ingest.detect import detect_platform
from app.ingest.instagram import ingest_instagram
from app.ingest.youtube import ingest_youtube
from app.rag.chain import build_chain_for_session
from app.rag.vector_store import upsert_chunks
from app.routes.ingest import _comments_to_chunks, _enrich_one


YT_URL = "https://youtube.com/shorts/OOkVHERHUbI?si=UOTeLzLYuP1w6B-0"
IG_URL = "https://www.instagram.com/reel/DXi739HDNpw/?igsh=MW4xbm5vODY4OG9heg=="


def _section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


async def _ingest_both(session_id: str) -> None:
    """Mirror routes/ingest.py without the FastAPI shell."""
    _section("Ingest video A (YouTube)")
    t = time.perf_counter()
    meta_a, segs_a = ingest_youtube(YT_URL, slot="A")
    print(f"  YT scrape+transcript in {time.perf_counter()-t:.1f}s -> {meta_a.creator}, "
          f"{meta_a.views:,} views, {meta_a.engagement_rate:.2f}% engagement")

    _section("Ingest video B (Instagram)")
    t = time.perf_counter()
    meta_b, segs_b = ingest_instagram(IG_URL, slot="B")
    print(f"  IG scrape+transcript in {time.perf_counter()-t:.1f}s -> {meta_b.creator}, "
          f"{meta_b.views:,} views, {meta_b.engagement_rate:.2f}% engagement")

    _section("Enrich both (comments + sentiment + trends)")
    t = time.perf_counter()
    (meta_a, comments_a), (meta_b, comments_b) = await asyncio.gather(
        _enrich_one(meta_a, segs_a),
        _enrich_one(meta_b, segs_b),
    )
    print(f"  Enriched in {time.perf_counter()-t:.1f}s")
    print(f"  A: trend={meta_a.topic_trend_status}, comments={len(comments_a)}, "
          f"sentiment={meta_a.comment_sentiment_mix}")
    print(f"  B: trend={meta_b.topic_trend_status}, comments={len(comments_b)}, "
          f"sentiment={meta_b.comment_sentiment_mix}")

    _section("Chunk + embed + upsert")
    t = time.perf_counter()
    chunks_a = chunk_transcript(segs_a, "A") + _comments_to_chunks(comments_a, "A")
    chunks_b = chunk_transcript(segs_b, "B") + _comments_to_chunks(comments_b, "B")
    n_a = upsert_chunks(session_id, meta_a.video_id, chunks_a)
    n_b = upsert_chunks(session_id, meta_b.video_id, chunks_b)
    print(f"  Stored A={n_a} B={n_b} chunks in {time.perf_counter()-t:.1f}s")

    sessions.save(session_id, meta_a, meta_b)


async def _ask(session_id: str, question: str) -> str:
    """Stream one question. Print tokens live, return the full answer."""
    chain = build_chain_for_session(session_id)
    config = {"configurable": {"session_id": session_id}}
    full = []
    print(f"\n>>> USER: {question}\n--- AI: ", end="", flush=True)
    async for token in chain.astream({"question": question}, config=config):
        if not token:
            continue
        full.append(token)
        # Best-effort live print; encode to ASCII to dodge cp1252 issues on Windows.
        try:
            print(token, end="", flush=True)
        except UnicodeEncodeError:
            print(token.encode("ascii", "replace").decode("ascii"), end="", flush=True)
    answer = "".join(full)
    print("\n")
    return answer


async def main() -> int:
    session_id = "smoke-chat-001"
    sessions.clear()

    t0 = time.perf_counter()
    await _ingest_both(session_id)

    _section("Q1: engagement rate")
    a1 = await _ask(session_id, "What is the engagement rate of each video?")

    _section("Q2: hooks")
    a2 = await _ask(session_id, "Compare the hooks in the first 5 seconds of A and B.")

    _section("Q3: WHY hypothesis")
    a3 = await _ask(session_id, "Why might Video A get different engagement than Video B?")

    _section("Q4: memory follow-up (uses 'its' from prior turn)")
    a4 = await _ask(session_id, "And what about its hashtag strategy?")

    _section("DONE")
    print(f"Total: {time.perf_counter() - t0:.1f}s")
    print(f"Q1 answer length: {len(a1)} chars")
    print(f"Q2 answer length: {len(a2)} chars")
    print(f"Q3 answer length: {len(a3)} chars")
    print(f"Q4 answer length: {len(a4)} chars")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
