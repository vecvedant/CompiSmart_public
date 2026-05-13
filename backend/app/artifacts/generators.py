"""Artifact generators.

Each generator is an async iterator that yields dict events. The chat route
forwards these as SSE frames to the frontend, which updates the artifact
panel live. Events:

    {"event": "artifact_create", "id", "kind", "title", "status": "pending"}
    {"event": "artifact_update", "id", "patch": {...}}        (many)
    {"event": "artifact_token",  "id", "field": "...", "text": "..."}  (streamed tokens)
    {"event": "artifact_done",   "id", "title", "payload": {...}}
    {"event": "artifact_error",  "id", "message"}

The full payload is also persisted to the artifacts table — once done, the
frontend can reload from DB without replaying the stream.

Generators implemented:
    compare  — side-by-side analysis of two assets (uses verdict.py)
    draft    — long-form drafted content (uses build/writer.py)
    summary  — quick brief across selected assets
    metrics  — engagement/sentiment/views per asset
    quotes   — best lines pulled from comments / transcripts
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import AsyncIterator, Optional

from langchain_google_genai import ChatGoogleGenerativeAI

from app import sessions, supabase_client
from app.artifacts.dispatcher import DispatchResult
from app.build.writer import run_build
from app.config import settings
from app.db import artifacts as art_db
from app.db import assets as assets_db
from app.db import drafts as drafts_db
from app.ingest.chunking import chunk_transcript
from app.models import (
    BuildRequest,
    Comment,
    CommentSentimentMix,
    TranscriptSegment,
    VideoMeta,
)
from app.rag.embeddings import embed_query
from app.rag.vector_store import search_assets, upsert_chunks
from app.rag.verdict import build_verdict, build_verdict_streaming
from app.routes.compare import _segments_from_body, _videometa_from_asset
from app.routes.ingest import _comments_to_chunks

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def generate_artifact(
    session_id: str,
    user_message: str,
    decision: DispatchResult,
) -> AsyncIterator[dict]:
    """Dispatch to the right generator. Yields stream events."""
    if decision.intent == "compare":
        async for ev in _compare_artifact(session_id, user_message, decision):
            yield ev
    elif decision.intent == "draft":
        async for ev in _draft_artifact(session_id, user_message, decision):
            yield ev
    elif decision.intent == "summary":
        async for ev in _summary_artifact(session_id, user_message, decision):
            yield ev
    elif decision.intent == "metrics":
        async for ev in _metrics_artifact(session_id, user_message, decision):
            yield ev
    elif decision.intent == "quotes":
        async for ev in _quotes_artifact(session_id, user_message, decision):
            yield ev
    else:
        return  # chat intent — no artifact


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

async def _fetch_session_assets(session_id: str, asset_ids: list[str]) -> list[dict]:
    rows = await supabase_client.list_assets(session_id)
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in asset_ids if i in by_id]


# ---------------------------------------------------------------------------
# Compare artifact
# ---------------------------------------------------------------------------

async def _compare_artifact(
    session_id: str, user_message: str, d: DispatchResult,
) -> AsyncIterator[dict]:
    sel = await _fetch_session_assets(session_id, d.asset_ids)
    sel = [a for a in sel if a.get("type") == "video" and a.get("ingest_status") == "ready"]
    if len(sel) < 2:
        # Defensive — dispatcher should have caught this. Emit a friendly error.
        artifact = await art_db.insert({
            "session_id": session_id, "kind": "compare", "status": "failed",
            "title": "Comparison not possible",
            "asset_ids": [], "prompt": user_message,
            "payload_json": {"error": "Need at least 2 ready video assets to compare."},
        })
        yield _evt("artifact_create", id=artifact["id"], kind="compare",
                   title=artifact["title"], status="failed")
        yield _evt("artifact_error", id=artifact["id"],
                   message="Need two video assets that are fully ingested to run a compare.")
        return

    a, b = sel[0], sel[1]
    initial = {
        "video_a": {"id": a["id"], "title": a["title"], "metadata": a.get("metadata_json") or {}},
        "video_b": {"id": b["id"], "title": b["title"], "metadata": b.get("metadata_json") or {}},
        "verdict": None,
        "streaming_preview": "",
    }
    artifact = await art_db.insert({
        "session_id": session_id, "kind": "compare", "status": "pending",
        "title": f"{(a['title'] or 'A')[:40]} vs {(b['title'] or 'B')[:40]}",
        "asset_ids": [a["id"], b["id"]], "prompt": user_message,
        "payload_json": initial,
    })
    aid = artifact["id"]
    yield _evt("artifact_create", id=aid, kind="compare", title=artifact["title"],
               status="pending", payload=initial)

    # Speed-up: build the VideoMeta objects + extract hooks from body_text
    # directly (no Qdrant round-trip), then kick off two things in parallel:
    #   1. Verdict streaming (the user-visible work)
    #   2. Chunk upsert for the compare-session (so subsequent sources panel
    #      + compare-session chat works — fire-and-forget, background)
    meta_a = _videometa_from_asset(a, "A")
    meta_b = _videometa_from_asset(b, "B")
    hook_a = (a.get("body_text") or "")[:600].strip() or "(no transcript)"
    hook_b = (b.get("body_text") or "")[:600].strip() or "(no transcript)"

    compare_session_id = uuid.uuid4().hex[:12]
    # Fire EVERYTHING in the background — sessions.save writes to Qdrant
    # (slow round-trip to wherever the cluster is), chunk upsert similarly.
    # The verdict only needs the metadata + hook strings we already have.
    asyncio.create_task(_bootstrap_compare_chunks(compare_session_id, a, b, meta_a, meta_b))
    asyncio.create_task(asyncio.to_thread(sessions.save, compare_session_id, meta_a, meta_b))

    yield _evt("artifact_update", id=aid, patch={"stage": "verdict", "compare_session_id": compare_session_id})

    # Stream verdict tokens as they arrive — drives the "live writing" feel.
    streaming_text = ""
    verdict = None
    try:
        async for kind_evt, payload_evt in build_verdict_streaming(meta_a, meta_b, hook_a, hook_b):
            if kind_evt == "token":
                streaming_text += payload_evt
                yield _evt("artifact_token", id=aid, field="streaming_preview", text=payload_evt)
            elif kind_evt == "done":
                verdict = payload_evt
    except Exception as e:
        log.exception("verdict streaming failed: %s", e)
        await art_db.update_payload(aid, {**initial, "error": str(e)}, status="failed")
        yield _evt("artifact_error", id=aid, message=str(e))
        return

    if verdict is None:
        await art_db.update_payload(aid, {**initial, "error": "no verdict produced"}, status="failed")
        yield _evt("artifact_error", id=aid, message="no verdict produced")
        return

    payload = {
        **initial,
        "compare_session_id": compare_session_id,
        "verdict": verdict.model_dump(),
        "streaming_preview": streaming_text,
    }
    title = _compose_compare_title(verdict, a, b)
    await art_db.update_payload(aid, payload, status="ready", title=title)
    yield _evt("artifact_done", id=aid, title=title, payload=payload)


async def _bootstrap_compare_chunks(
    compare_session_id: str, a: dict, b: dict, meta_a: VideoMeta, meta_b: VideoMeta,
) -> None:
    """Background fire-and-forget: upsert A/B-tagged chunks so the legacy
    sources panel + compare-session chat have data. Failures are non-fatal.
    """
    try:
        segs_a = _segments_from_body(a.get("body_text") or "")
        segs_b = _segments_from_body(b.get("body_text") or "")
        chunks_a = chunk_transcript(segs_a, video_slot="A", target_tokens=150, overlap_tokens=30) if segs_a else []
        chunks_b = chunk_transcript(segs_b, video_slot="B", target_tokens=150, overlap_tokens=30) if segs_b else []
        chunks_a += _comments_to_chunks(meta_a.top_comments, slot="A")
        chunks_b += _comments_to_chunks(meta_b.top_comments, slot="B")
        await asyncio.gather(
            asyncio.to_thread(upsert_chunks, compare_session_id, meta_a.video_id, chunks_a),
            asyncio.to_thread(upsert_chunks, compare_session_id, meta_b.video_id, chunks_b),
        )
        log.info("compare chunks upserted (background) for session=%s", compare_session_id)
    except Exception as e:
        log.warning("compare bg chunk upsert failed: %s", e)


def _compose_compare_title(verdict, a: dict, b: dict) -> str:
    winner = verdict.winning_video
    if winner == "A":
        return f"Winner: {(a['title'] or 'A')[:50]}"
    if winner == "B":
        return f"Winner: {(b['title'] or 'B')[:50]}"
    return f"{(a['title'] or 'A')[:40]} vs {(b['title'] or 'B')[:40]}"


# ---------------------------------------------------------------------------
# Draft artifact
# ---------------------------------------------------------------------------

async def _draft_artifact(
    session_id: str, user_message: str, d: DispatchResult,
) -> AsyncIterator[dict]:
    sel = await _fetch_session_assets(session_id, d.asset_ids)
    sel = [a for a in sel if a.get("ingest_status") == "ready"]
    if not sel:
        artifact = await art_db.insert({
            "session_id": session_id, "kind": "draft", "status": "failed",
            "title": "No ready assets to draft from",
            "asset_ids": [], "prompt": user_message,
            "payload_json": {"error": "No ready assets in session."},
        })
        yield _evt("artifact_create", id=artifact["id"], kind="draft",
                   title=artifact["title"], status="failed")
        yield _evt("artifact_error", id=artifact["id"],
                   message="Add some articles or videos first, then ask me to draft.")
        return

    initial = {
        "output_type": d.output_type or "blog_post",
        "tone": d.tone or "confident",
        "length": d.length or "medium",
        "instruction": d.instruction or user_message,
        "bullets": [],
        "content_md": "",
        "asset_titles": [a["title"] for a in sel],
    }
    title = f"{_label(d.output_type)} from {len(sel)} asset{'s' if len(sel) != 1 else ''}"
    artifact = await art_db.insert({
        "session_id": session_id, "kind": "draft", "status": "pending",
        "title": title, "asset_ids": [a["id"] for a in sel],
        "prompt": user_message, "payload_json": initial,
    })
    aid = artifact["id"]
    yield _evt("artifact_create", id=aid, kind="draft", title=title,
               status="pending", payload=initial)

    req = BuildRequest(
        session_id=session_id,
        asset_ids=[a["id"] for a in sel],
        output_type=initial["output_type"],   # type: ignore[arg-type]
        tone=initial["tone"],                  # type: ignore[arg-type]
        length=initial["length"],              # type: ignore[arg-type]
        instruction=initial["instruction"],
        chat_context_turns=4,
    )

    bullets: list[str] = []
    content: list[str] = []
    try:
        async for ev in run_build(req, sel):
            stage = ev.get("stage")
            if stage == "outline":
                bullets = ev["bullets"]
                yield _evt("artifact_update", id=aid, patch={"bullets": bullets})
            elif stage == "expand":
                yield _evt("artifact_update", id=aid, patch={"sections_drafted": ev["section_count"]})
            elif stage == "polish_token":
                content.append(ev["text"])
                yield _evt("artifact_token", id=aid, field="content_md", text=ev["text"])
            elif stage == "done":
                pass
    except Exception as e:
        log.exception("draft generator failed: %s", e)
        await art_db.update_payload(aid, {**initial, "bullets": bullets, "error": str(e)}, status="failed")
        yield _evt("artifact_error", id=aid, message=str(e))
        return

    final_md = _strip_em_dashes("".join(content).strip())
    final = {**initial, "bullets": bullets, "content_md": final_md}
    final_title = _extract_md_title(final_md) or title
    await art_db.update_payload(aid, final, status="ready", title=final_title)

    # Also persist to the drafts table so DraftsView shows chat-spawned drafts.
    # The drafts row links back to the artifact via metadata.
    try:
        saved_draft = await drafts_db.upsert({
            "session_id": session_id,
            "asset_ids": [a["id"] for a in sel],
            "output_type": initial["output_type"],
            "tone": initial["tone"],
            "length": initial["length"],
            "title": final_title,
            "content_md": final_md,
        })
        # Stash the draft_id back on the artifact payload so the UI can deep-link.
        final["draft_id"] = saved_draft.get("id")
        await art_db.update_payload(aid, final, status="ready", title=final_title)
    except Exception as e:
        log.warning("draft save (chat-spawned) failed: %s", e)

    yield _evt("artifact_done", id=aid, title=final_title, payload=final)


def _label(output_type: Optional[str]) -> str:
    return {
        "blog_post": "Blog post",
        "video_script": "Video script",
        "x_thread": "X thread",
        "linkedin_post": "LinkedIn post",
        "newsletter": "Newsletter",
    }.get(output_type or "", "Draft")


def _extract_md_title(md: str) -> Optional[str]:
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()[:200]
    return None


# Belt-and-suspenders: even with anti-em-dash prompting, models occasionally
# emit them. We post-process to remove every em-dash variant. " — " becomes
# ", " or ". " depending on which reads better; bare "—" becomes "–" only
# when it joins numbers (preserves ranges like "5–10").
_EM_DASH_RE = __import__("re").compile(r"\s*[—–]\s*")


def _strip_em_dashes(text: str) -> str:
    """Replace em-dashes and en-dashes with comma + space, preserving numeric
    ranges ('5-10' style). Idempotent.
    """
    if not text:
        return text
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in ("—", "–"):
            # Numeric range guard: digit on both sides → use hyphen-minus
            prev = text[i - 1] if i > 0 else " "
            nxt = text[i + 1] if i + 1 < n else " "
            if prev.isdigit() and nxt.isdigit():
                out.append("-")
            else:
                # Eat surrounding whitespace, write ", "
                while out and out[-1] == " ":
                    out.pop()
                # Skip following whitespace
                j = i + 1
                while j < n and text[j] == " ":
                    j += 1
                out.append(", ")
                i = j
                continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Summary artifact
# ---------------------------------------------------------------------------

_SUMMARY_SYSTEM = """You write a punchy brief summarizing a set of saved content assets.

Output STRICT JSON with these keys (no prose around it):
  headline  — one sentence capturing the through-line across all assets
  bullets   — array of 4-7 short bullets, each ONE sentence, citing the asset with [asset:N]
  takeaway  — one sentence: the so-what for a content creator looking at this material

Be direct. Use specific names, numbers, and facts from the assets. No hedging."""


async def _summary_artifact(
    session_id: str, user_message: str, d: DispatchResult,
) -> AsyncIterator[dict]:
    sel = await _fetch_session_assets(session_id, d.asset_ids)
    sel = [a for a in sel if a.get("ingest_status") == "ready"]
    if not sel:
        async for ev in _no_assets("summary", session_id, user_message, "Nothing to summarize", "Add some assets first."):
            yield ev
        return

    initial = {"asset_titles": [a["title"] for a in sel], "headline": "", "bullets": [], "takeaway": ""}
    artifact = await art_db.insert({
        "session_id": session_id, "kind": "summary", "status": "pending",
        "title": f"Summary of {len(sel)} asset{'s' if len(sel) != 1 else ''}",
        "asset_ids": [a["id"] for a in sel], "prompt": user_message,
        "payload_json": initial,
    })
    aid = artifact["id"]
    yield _evt("artifact_create", id=aid, kind="summary", title=artifact["title"],
               status="pending", payload=initial)

    context = _build_asset_context(sel)
    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.google_api_key,
        temperature=0.4,
        max_output_tokens=1024,
    )
    user = f"USER NOTE: {user_message}\n\nASSETS:\n{context}\n\nWrite the JSON brief now."
    raw = ""
    try:
        # Stream tokens so the user sees the brief being written live.
        async for chunk in llm.astream([("system", _SUMMARY_SYSTEM), ("human", user)]):
            content = getattr(chunk, "content", "") or ""
            if isinstance(content, list):
                content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
            if content:
                raw += content
                yield _evt("artifact_token", id=aid, field="streaming_preview", text=content)
        data = _safe_json(raw) or {}
    except Exception as e:
        log.exception("summary LLM failed: %s", e)
        data = {}

    payload = {
        **initial,
        "headline": data.get("headline") or "",
        "bullets": [b for b in (data.get("bullets") or []) if isinstance(b, str)],
        "takeaway": data.get("takeaway") or "",
    }
    title = (payload["headline"][:100]) or artifact["title"]
    await art_db.update_payload(aid, payload, status="ready", title=title)
    yield _evt("artifact_done", id=aid, title=title, payload=payload)


def _build_asset_context(sel: list[dict]) -> str:
    parts = []
    for i, a in enumerate(sel):
        title = (a.get("title") or "")[:200]
        body = (a.get("body_text") or "").replace("\n", " ")[:1200]
        parts.append(f"[asset:{i+1}] ({a.get('type')}) {title}\n{body}")
    return "\n\n".join(parts)


def _safe_json(text: str) -> Optional[dict]:
    import re as _re
    text = (text or "").strip()
    if text.startswith("```"):
        text = _re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = _re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _re.search(r"\{.*\}", text, flags=_re.DOTALL)
        if m:
            try: return json.loads(m.group(0))
            except json.JSONDecodeError: return None
    return None


# ---------------------------------------------------------------------------
# Metrics artifact
# ---------------------------------------------------------------------------

async def _metrics_artifact(
    session_id: str, user_message: str, d: DispatchResult,
) -> AsyncIterator[dict]:
    sel = await _fetch_session_assets(session_id, d.asset_ids)
    sel = [a for a in sel if a.get("ingest_status") == "ready"]
    if not sel:
        async for ev in _no_assets("metrics", session_id, user_message, "No assets to measure", "Add some assets first."):
            yield ev
        return

    rows = []
    for i, a in enumerate(sel):
        meta = a.get("metadata_json") or {}
        sentiment = meta.get("comment_sentiment_mix") or {}
        rows.append({
            "idx": i + 1,
            "asset_id": a["id"],
            "title": a["title"],
            "type": a.get("type"),
            "creator": meta.get("creator"),
            "views": meta.get("views"),
            "likes": meta.get("likes"),
            "comments": meta.get("comments"),
            "engagement_rate": meta.get("engagement_rate"),
            "view_velocity": meta.get("view_velocity"),
            "life_stage": meta.get("life_stage"),
            "topic_trend_status": meta.get("topic_trend_status"),
            "discussion_depth": meta.get("discussion_depth"),
            "sentiment": sentiment,
            "top_keywords": (meta.get("topic_keywords") or [])[:6],
        })

    payload = {"rows": rows}
    title = f"Metrics for {len(rows)} asset{'s' if len(rows) != 1 else ''}"
    artifact = await art_db.insert({
        "session_id": session_id, "kind": "metrics", "status": "ready",
        "title": title, "asset_ids": [a["id"] for a in sel],
        "prompt": user_message, "payload_json": payload,
    })
    yield _evt("artifact_create", id=artifact["id"], kind="metrics",
               title=title, status="ready", payload=payload)
    yield _evt("artifact_done", id=artifact["id"], title=title, payload=payload)


# ---------------------------------------------------------------------------
# Quotes artifact
# ---------------------------------------------------------------------------

_QUOTES_SYSTEM = """You pick out the sharpest QUOTES from a set of content assets.

You're given retrieved chunks (transcript bits and comments). Pick 5-8 quotes
that would actually make a content creator stop scrolling. Bias toward:
  - specific, vivid lines (not generic statements)
  - emotional comments (surprise, frustration, delight, push-back)
  - punchy transcript moments (hooks, one-liners, callbacks)

Output STRICT JSON, no prose around it:
{"quotes": [
  {"text": "exact quote", "source": "asset N (transcript)" or "asset N (comment)", "why": "one short sentence on what makes it good"}
]}"""


async def _quotes_artifact(
    session_id: str, user_message: str, d: DispatchResult,
) -> AsyncIterator[dict]:
    sel = await _fetch_session_assets(session_id, d.asset_ids)
    sel = [a for a in sel if a.get("ingest_status") == "ready"]
    if not sel:
        async for ev in _no_assets("quotes", session_id, user_message, "No assets to quote", "Add some assets first."):
            yield ev
        return

    title = f"Best quotes from {len(sel)} asset{'s' if len(sel) != 1 else ''}"
    initial = {"quotes": []}
    artifact = await art_db.insert({
        "session_id": session_id, "kind": "quotes", "status": "pending",
        "title": title, "asset_ids": [a["id"] for a in sel],
        "prompt": user_message, "payload_json": initial,
    })
    aid = artifact["id"]
    yield _evt("artifact_create", id=aid, kind="quotes", title=title,
               status="pending", payload=initial)

    # Retrieve juicy chunks across all selected assets.
    asset_ids = [a["id"] for a in sel]
    qvec = await asyncio.to_thread(embed_query, user_message or "best quotes")
    body_chunks = await asyncio.to_thread(search_assets, asset_ids, qvec, kind=None, limit=20)
    comment_chunks = await asyncio.to_thread(search_assets, asset_ids, qvec, kind="comment", limit=10)
    # Map asset_id -> 1-based index
    idx = {a["id"]: i + 1 for i, a in enumerate(sel)}

    def fmt(chunk: dict) -> str:
        pos = idx.get(chunk.get("asset_id"), "?")
        kind = chunk.get("kind") or "transcript"
        text = (chunk.get("text") or "").replace("\n", " ").strip()
        return f"[asset:{pos} ({kind})] {text[:400]}"

    context = "\n".join(fmt(c) for c in (body_chunks + comment_chunks))

    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.google_api_key,
        temperature=0.5,
        max_output_tokens=1024,
    )
    raw = ""
    try:
        async for chunk in llm.astream(
            [("system", _QUOTES_SYSTEM),
             ("human", f"USER NOTE: {user_message}\n\nCHUNKS:\n{context}\n\nReturn JSON.")],
        ):
            content = getattr(chunk, "content", "") or ""
            if isinstance(content, list):
                content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
            if content:
                raw += content
                yield _evt("artifact_token", id=aid, field="streaming_preview", text=content)
        data = _safe_json(raw) or {}
    except Exception as e:
        log.exception("quotes LLM failed: %s", e)
        data = {}

    quotes = []
    for q in (data.get("quotes") or []):
        if not isinstance(q, dict): continue
        text = (q.get("text") or "").strip()
        if not text: continue
        quotes.append({
            "text": text,
            "source": (q.get("source") or "").strip(),
            "why": (q.get("why") or "").strip(),
        })

    payload = {"quotes": quotes}
    await art_db.update_payload(aid, payload, status="ready", title=title)
    yield _evt("artifact_done", id=aid, title=title, payload=payload)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _no_assets(kind, session_id, prompt, title, message) -> AsyncIterator[dict]:
    artifact = await art_db.insert({
        "session_id": session_id, "kind": kind, "status": "failed",
        "title": title, "asset_ids": [], "prompt": prompt,
        "payload_json": {"error": message},
    })
    yield _evt("artifact_create", id=artifact["id"], kind=kind,
               title=title, status="failed")
    yield _evt("artifact_error", id=artifact["id"], message=message)


def _evt(event: str, **fields) -> dict:
    return {"event": event, **fields}
