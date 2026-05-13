"""POST /api/chat -- streams a Gemini answer as Server-Sent Events.

Frontend opens this with `fetch()` + ReadableStream (or EventSource for GET-style
endpoints). Each `data:` line carries one chunk of text the model emitted.
A final `event: done` signals end-of-stream. Errors mid-stream surface as
`event: error`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app import sessions, supabase_client
from app.artifacts.dispatcher import DispatchResult, classify_intent
from app.artifacts.generators import generate_artifact
from app.db import chat as chat_db
from app.models import ChatRequest, WebSource
from app.rag.chain import build_chain_for_assets, build_chain_for_session
from app.rag.web_sources import record_web_sources

log = logging.getLogger(__name__)
router = APIRouter()

# Retry config for transient upstream Gemini failures (503 high-demand,
# 429 rate-limit, occasional 500 server-side hiccups). We only retry
# BEFORE any tokens have streamed -- mid-stream errors can't be recovered
# without re-running the whole chain, which would duplicate the user-
# visible answer.
_TRANSIENT_RETRIES = 2
_TRANSIENT_BACKOFF = (1.5, 4.0)  # seconds for retry attempts 1 and 2


def _is_transient_upstream_error(e: BaseException) -> bool:
    """Best-effort match on Gemini's transient error shapes.

    google-api-core raises ResourceExhausted (429), ServiceUnavailable
    (503), InternalServerError (500). We match on class name to avoid
    importing yet another dependency just for isinstance checks.
    """
    name = type(e).__name__
    if name in {"ResourceExhausted", "ServiceUnavailable", "InternalServerError"}:
        return True
    msg = str(e)
    # Fallback: catch the SDK's wrapper exceptions that include the code.
    return any(code in msg for code in ("503", "429", "high demand", "overloaded"))


def _sse(data: dict, event: str | None = None) -> str:
    """Format a single Server-Sent Event frame."""
    out = []
    if event:
        out.append(f"event: {event}")
    out.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    out.append("")  # blank line ends the event
    return "\n".join(out) + "\n"


def _extract_web_sources(message: Any) -> list[WebSource]:
    """Pull cited web pages out of a Gemini grounding-metadata blob.

    The shape is unstable across langchain-google-genai versions and across
    Gemini's own API. We probe a few known locations and fall back to []
    rather than crashing the chat stream over metadata parsing.
    """
    if message is None:
        return []
    md = getattr(message, "response_metadata", None) or {}
    addl = getattr(message, "additional_kwargs", None) or {}
    gm = md.get("grounding_metadata") or addl.get("grounding_metadata")
    if not gm:
        return []

    # Both snake_case and camelCase have shown up in different versions.
    if isinstance(gm, dict):
        chunks = gm.get("grounding_chunks") or gm.get("groundingChunks") or []
    else:
        chunks = getattr(gm, "grounding_chunks", None) or []

    out: list[WebSource] = []
    for c in chunks:
        web = c.get("web") if isinstance(c, dict) else getattr(c, "web", None)
        if not web:
            continue
        if isinstance(web, dict):
            uri = web.get("uri") or web.get("url")
            title = web.get("title") or ""
        else:
            uri = getattr(web, "uri", None) or getattr(web, "url", None)
            title = getattr(web, "title", "") or ""
        if uri:
            out.append(WebSource(url=uri, title=title or "", snippet=""))
    return out


async def _resolve_chain(session_id: str):
    """Pick the chain: asset-mode if the session has saved assets,
    otherwise fall back to the legacy two-video compare chain."""
    if supabase_client.is_configured():
        try:
            assets = await supabase_client.list_assets(session_id)
        except Exception as e:
            log.warning("list_assets failed for chat session=%s: %s", session_id, e)
            assets = []
        ready = [a for a in assets if a.get("ingest_status") == "ready"]
        if ready:
            log.info("chat session=%s assets=%d (asset-mode)", session_id, len(ready))
            return build_chain_for_assets(session_id, ready)

    # Legacy: two-video compare session
    if sessions.get(session_id):
        return build_chain_for_session(session_id)

    raise ValueError(f"session {session_id!r} has no assets and no compare data")


def _short_artifact_preamble(decision: DispatchResult) -> str:
    """Build the brief conversational reply that prefixes an artifact stream."""
    if decision.intent == "compare":
        return "Comparing those two — building the artifact below."
    if decision.intent == "draft":
        kind = {
            "blog_post": "blog post",
            "video_script": "video script",
            "x_thread": "X thread",
            "linkedin_post": "LinkedIn post",
            "newsletter": "newsletter",
        }.get(decision.output_type or "", "draft")
        return f"Drafting a {kind} for you — artifact coming up below."
    if decision.intent == "summary":
        return "Building a quick brief from your assets."
    if decision.intent == "metrics":
        return "Pulling engagement and sentiment metrics."
    if decision.intent == "quotes":
        return "Picking out the sharpest quotes."
    return ""


def _clarification_preamble(decision: DispatchResult) -> str:
    """Friendly one-liner before the MCQ card renders."""
    if decision.intent == "compare":
        return "Quick check before I run the comparison —"
    if decision.intent == "draft":
        return "Got it — one question before I write —"
    return "Quick question —"


@router.post("/chat")
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    config = {"configurable": {"session_id": req.session_id}}

    # First: classify intent. If it's an artifact intent, run that pipeline
    # and skip the full RAG chat chain (much faster + dedicated UX).
    # Fan out the two slow DB calls (assets list + chat history) in parallel.
    async def _fetch_recent_user_msgs() -> list[str]:
        if not supabase_client.is_configured():
            return []
        try:
            msgs = await chat_db.list_for_session(req.session_id)
        except Exception as e:
            log.warning("chat history fetch failed: %s", e)
            return []
        return [m["content"] for m in msgs if m.get("role") == "user"][-6:]

    async def _fetch_assets() -> list[dict]:
        if not supabase_client.is_configured():
            return []
        try:
            return await supabase_client.list_assets(req.session_id)
        except Exception as e:
            log.warning("dispatch list_assets failed: %s", e)
            return []

    assets_for_dispatch, recent_msgs = await asyncio.gather(
        _fetch_assets(), _fetch_recent_user_msgs()
    )
    ready_assets = [a for a in assets_for_dispatch if a.get("ingest_status") == "ready"]

    decision = await asyncio.to_thread(
        classify_intent, req.message, ready_assets, recent_msgs,
    )
    log.info("dispatch session=%s intent=%s asset_ids=%d clarify=%s reason=%s",
             req.session_id, decision.intent, len(decision.asset_ids),
             bool(decision.clarification), decision.reasoning[:80])

    # Persist the user message ONLY for paths that bypass the LCEL chain
    # (artifacts + clarifications). For pure-chat intent, RunnableWithMessage-
    # History saves it automatically — saving here too would duplicate the row.
    # We save BEFORE the artifact runs so the *next* request's dispatcher
    # sees this user message in its context, breaking the MCQ-answer loop.
    if (decision.is_artifact or decision.needs_clarification) and supabase_client.is_configured():
        try:
            next_idx = await chat_db.next_turn_idx(req.session_id)
            await chat_db.insert(req.session_id, next_idx, "user", req.message)
        except Exception as e:
            log.warning("user-message persist failed: %s", e)

    async def artifact_stream():
        preamble = _short_artifact_preamble(decision)
        if preamble:
            yield _sse({"token": preamble})
        try:
            async for ev in generate_artifact(req.session_id, req.message, decision):
                event_name = ev.get("event", "")
                payload = {k: v for k, v in ev.items() if k != "event"}
                yield _sse(payload, event=event_name)
        except Exception as e:
            log.exception("artifact stream failed: %s", e)
            yield _sse({"error": str(e)}, event="error")
            return
        yield _sse({"done": True}, event="done")

    async def clarification_stream():
        """Ask the user a structured follow-up instead of guessing."""
        intro = _clarification_preamble(decision)
        if intro:
            yield _sse({"token": intro})
        c = decision.clarification
        if c:
            yield _sse(c.to_dict(), event="clarification")
        yield _sse({"done": True}, event="done")

    if decision.needs_clarification:
        return StreamingResponse(
            clarification_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if decision.is_artifact:
        return StreamingResponse(
            artifact_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def stream():
        try:
            chain = await _resolve_chain(req.session_id)
        except ValueError as e:
            yield _sse({"error": str(e)}, event="error")
            return

        # We accumulate the streamed AIMessageChunks so we can read the
        # grounding metadata off the merged final message after the stream
        # ends. AIMessageChunk supports `+`; concatenation merges content
        # and metadata.
        accumulated = None
        # Transient-upstream retry: Gemini Flash on free tier occasionally
        # returns 503 ("This model is currently experiencing high demand")
        # or 429 spikes. We retry a couple of times before any tokens have
        # been emitted to the client, with short backoff. Once the first
        # token has streamed we cannot retry without showing duplicate
        # output, so mid-stream errors fall through to the client.
        attempt = 0
        while True:
            try:
                async for chunk in chain.astream(
                    {"question": req.message}, config=config
                ):
                    accumulated = chunk if accumulated is None else accumulated + chunk
                    content = getattr(chunk, "content", None) or ""
                    if isinstance(content, list):
                        # Gemini sometimes streams content as a list of parts.
                        content = "".join(
                            p.get("text", "") if isinstance(p, dict) else str(p)
                            for p in content
                        )
                    if not content:
                        continue
                    yield _sse({"token": content})
                break  # stream completed successfully
            except Exception as e:  # noqa: BLE001 -- surface to client cleanly
                already_streamed = accumulated is not None and bool(
                    getattr(accumulated, "content", "")
                )
                if (
                    not already_streamed
                    and attempt < _TRANSIENT_RETRIES
                    and _is_transient_upstream_error(e)
                ):
                    backoff = _TRANSIENT_BACKOFF[attempt]
                    log.warning(
                        "chat upstream transient (%s); retry %d/%d after %.1fs",
                        type(e).__name__, attempt + 1, _TRANSIENT_RETRIES, backoff,
                    )
                    await asyncio.sleep(backoff)
                    attempt += 1
                    accumulated = None
                    continue
                log.exception("chat stream failed: %s", e)
                # Friendlier message for the most common transient case so
                # the demo UI doesn't show a raw stack-y string.
                if _is_transient_upstream_error(e):
                    msg = (
                        "Gemini is overloaded right now. Please try the "
                        "question again in a moment."
                    )
                else:
                    msg = str(e)
                yield _sse({"error": msg}, event="error")
                return

        # After streaming completes, lift the cited web pages off the merged
        # message and stash them on the session so the Sources panel can
        # render them. We also push them down the SSE so the frontend can
        # update without a separate fetch.
        new_sources = _extract_web_sources(accumulated)
        if new_sources:
            record_web_sources(req.session_id, new_sources)
            yield _sse(
                {"sources": [s.model_dump() for s in new_sources]},
                event="sources",
            )
        yield _sse({"done": True}, event="done")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering (e.g. Cloud Run)
        },
    )
