"""LCEL chain: retrieve -> prompt -> Gemini streaming -> string tokens.

We rebuild the chain per session because the system prompt is per-session
(it carries the two videos' metadata block). The retrieval lambda closes
over the session_id so we don't have to thread it through RunnableConfig.
RunnableWithMessageHistory wraps the whole thing so memory persists across
turns within a session.
"""

from __future__ import annotations

import asyncio
import logging

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_google_genai import ChatGoogleGenerativeAI

from app import sessions, supabase_client
from app.config import settings
from app.rag.embeddings import embed_query
from app.rag.memory import get_session_history
from app.rag.prompts import (
    RETRIEVAL_BUDGETS,
    ROUTER_SYSTEM_PROMPT,
    build_assets_system_prompt,
    build_system_prompt,
    format_asset_chunks,
    format_chunks,
)
from app.rag.vector_store import search, search_assets

log = logging.getLogger(__name__)

# Per-video limits at retrieval time. Total context = 2 * (TOP_TRANSCRIPT + TOP_COMMENT).
TOP_TRANSCRIPT_PER_SLOT = 3
TOP_COMMENT_PER_SLOT = 2


def _retrieve_for_session(session_id: str):
    """Closure: returns a function that takes {"question": ...} and yields the
    formatted context string. Closes over session_id so the chain doesn't have
    to know about RunnableConfig.

    v2 speed: 4 Qdrant calls go out in parallel via asyncio.gather instead of
    serially. With Qdrant in the same region as Cloud Run, this drops retrieval
    latency from ~4×RTT to ~1×RTT.
    """

    def _retrieve(inputs: dict) -> str:
        question = inputs["question"]
        if not question:
            return "(empty question)"
        qvec = embed_query(question)

        async def _gather() -> list[dict]:
            tasks = [
                asyncio.to_thread(search, session_id, qvec, video_slot="A", kind="transcript", limit=TOP_TRANSCRIPT_PER_SLOT),
                asyncio.to_thread(search, session_id, qvec, video_slot="A", kind="comment", limit=TOP_COMMENT_PER_SLOT),
                asyncio.to_thread(search, session_id, qvec, video_slot="B", kind="transcript", limit=TOP_TRANSCRIPT_PER_SLOT),
                asyncio.to_thread(search, session_id, qvec, video_slot="B", kind="comment", limit=TOP_COMMENT_PER_SLOT),
            ]
            results = await asyncio.gather(*tasks)
            out: list[dict] = []
            for r in results:
                out.extend(r)
            return out

        try:
            chunks = asyncio.run(_gather())
        except RuntimeError:
            # Inside a running loop (chain.astream path). Fall back to sync
            # serial — caller is rare in practice (LCEL pulls retrieve from
            # a sync RunnableLambda).
            chunks = []
            for slot in ("A", "B"):
                chunks.extend(search(session_id, qvec, video_slot=slot, kind="transcript", limit=TOP_TRANSCRIPT_PER_SLOT))
                chunks.extend(search(session_id, qvec, video_slot=slot, kind="comment", limit=TOP_COMMENT_PER_SLOT))

        log.info("retrieve session=%s -> %d chunks (A+B transcript+comment)", session_id, len(chunks))
        return format_chunks(chunks)

    return _retrieve


def build_chain_for_session(session_id: str):
    """Build a fully-wired RAG chat chain for one session. Stream-ready.

    Raises ValueError if the session doesn't exist (caller should 404 it).
    """
    session_data = sessions.get(session_id)
    if not session_data:
        raise ValueError(f"session {session_id!r} not found")

    meta_a = session_data["A"]
    meta_b = session_data["B"]

    prompt = ChatPromptTemplate.from_messages([
        ("system", build_system_prompt(meta_a, meta_b)),
        MessagesPlaceholder("history"),
        ("human", "{question}\n\nRetrieved chunks:\n{context}"),
    ])

    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.google_api_key,
        temperature=0.4,
        # Headroom for thinking tokens + the actual answer with caveats.
        max_output_tokens=4096,
    )

    # Turn ON Gemini's built-in Google Search grounding. langchain-google-genai
    # 4.x recognizes the `{"google_search": {}}` tool dict natively and parses
    # grounding_metadata into response_metadata. routes/chat.py reads that to
    # emit [web:N] citations.
    llm_with_search = llm.bind_tools([{"google_search": {}}])

    # NOTE: no StrOutputParser at the tail. We need the AIMessageChunk
    # objects so we can pull grounding metadata off the final chunk.
    # RunnableWithMessageHistory accepts BaseMessage outputs and stores
    # them in history correctly.
    base_chain = (
        RunnablePassthrough.assign(context=RunnableLambda(_retrieve_for_session(session_id)))
        | prompt
        | llm_with_search
    )

    return RunnableWithMessageHistory(
        base_chain,
        get_session_history,
        input_messages_key="question",
        history_messages_key="history",
    )


# ===========================================================================
# v2 — asset-based chain
# ===========================================================================

def _classify_route(question: str) -> str:
    """One cheap Gemini-Lite call → route label. Falls back to 'mixed' on
    any error or unrecognized output."""
    try:
        llm = ChatGoogleGenerativeAI(
            model=settings.gemini_classifier_model,
            google_api_key=settings.google_api_key,
            temperature=0.0,
            max_output_tokens=8,
        )
        msg = llm.invoke([
            ("system", ROUTER_SYSTEM_PROMPT),
            ("human", question),
        ])
        raw = (getattr(msg, "content", "") or "").strip().lower()
        for token in ("factual", "summary", "comparative", "current", "mixed"):
            if token in raw:
                return token
    except Exception as e:  # noqa: BLE001
        log.warning("router classify failed: %s", e)
    return "mixed"


def _retrieve_for_assets(session_id: str, assets: list[dict]):
    """Closure: takes {"question": ...} → formatted context string.

    Routing-aware: first asks Gemini-Lite which kind of question this is,
    then picks chunk budgets accordingly. Searches across all session assets
    in parallel (one body search + one comment search), then evenly per-asset.
    """
    asset_ids = [a["id"] for a in assets]
    asset_index = {a["id"]: i + 1 for i, a in enumerate(assets)}

    def _retrieve(inputs: dict) -> str:
        question = inputs["question"]
        if not question or not asset_ids:
            return "(no assets in session — ask the user to add news articles or videos from the feed)"

        route = _classify_route(question)
        budget = RETRIEVAL_BUDGETS.get(route, RETRIEVAL_BUDGETS["mixed"])
        log.info("router session=%s route=%s budget=%s", session_id, route, budget)

        qvec = embed_query(question)

        async def _gather() -> list[dict]:
            # We pull `body` (article+transcript) and `comment` in parallel,
            # then per-asset cap in post.
            tasks = [
                asyncio.to_thread(search_assets, asset_ids, qvec, kind="article_body", limit=budget["body"]),
                asyncio.to_thread(search_assets, asset_ids, qvec, kind="transcript", limit=budget["body"]),
                asyncio.to_thread(search_assets, asset_ids, qvec, kind="comment", limit=budget["comment"]),
            ]
            results = await asyncio.gather(*tasks)
            merged = results[0] + results[1] + results[2]
            return _per_asset_cap(merged, budget["per_asset_cap"])

        try:
            chunks = asyncio.run(_gather())
        except RuntimeError:
            article_chunks = search_assets(asset_ids, qvec, kind="article_body", limit=budget["body"])
            transcript_chunks = search_assets(asset_ids, qvec, kind="transcript", limit=budget["body"])
            comment_chunks = search_assets(asset_ids, qvec, kind="comment", limit=budget["comment"])
            chunks = _per_asset_cap(
                article_chunks + transcript_chunks + comment_chunks,
                budget["per_asset_cap"],
            )

        log.info("retrieve-assets session=%s -> %d chunks (route=%s)", session_id, len(chunks), route)
        return format_asset_chunks(chunks, asset_index)

    return _retrieve


def _per_asset_cap(chunks: list[dict], cap: int) -> list[dict]:
    """Trim per-asset chunks so one verbose asset doesn't dominate the prompt.
    Keeps order; drops lowest-scoring extras when an asset exceeds cap.
    """
    if cap <= 0:
        return chunks
    by_asset: dict[str, list[dict]] = {}
    for c in chunks:
        by_asset.setdefault(c.get("asset_id") or "", []).append(c)
    kept: list[dict] = []
    for aid, items in by_asset.items():
        items.sort(key=lambda x: x.get("score") or 0, reverse=True)
        kept.extend(items[:cap])
    kept.sort(key=lambda x: x.get("score") or 0, reverse=True)
    return kept


def build_chain_for_assets(session_id: str, assets: list[dict]):
    """Asset-mode RAG chain. `assets` is the list of Supabase asset rows for
    this session, in display order. Returns a RunnableWithMessageHistory
    that streams Gemini tokens.

    Google Search grounding is enabled via the 4.x-native `{"google_search": {}}`
    tool dict — grounding_metadata is parsed by langchain-google-genai itself
    (see chat_models.py line ~1218) and ends up in response_metadata, which
    routes/chat.py reads to emit [web:N] citations.
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", build_assets_system_prompt(assets)),
        MessagesPlaceholder("history"),
        ("human", "{question}\n\nRetrieved chunks:\n{context}"),
    ])

    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.google_api_key,
        temperature=0.4,
        max_output_tokens=4096,
    )
    llm_with_search = llm.bind_tools([{"google_search": {}}])

    base_chain = (
        RunnablePassthrough.assign(context=RunnableLambda(_retrieve_for_assets(session_id, assets)))
        | prompt
        | llm_with_search
    )

    return RunnableWithMessageHistory(
        base_chain,
        get_session_history,
        input_messages_key="question",
        history_messages_key="history",
    )
