"""3-stage writer for Build mode.

  outline → expand → polish

Stage 1 (outline) — Gemini Flash with assets metadata + user instruction.
  Output: 5-7 bullets describing the structure of the piece.

Stage 2 (expand) — for each bullet, retrieve top-K chunks from Qdrant across
  the selected asset_ids and ask Gemini to write that section, citing the
  specific assets/quotes/numbers that back it up.

Stage 3 (polish) — single pass over the joined draft with an anti-AI prompt
  that strips clichés, varies sentence length, and tightens the prose to the
  target length and tone. This pass is streamed to the client.

Citations use [asset:N] (1-based session index) so the frontend can render
clickable chips that link back to the asset.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from langchain_google_genai import ChatGoogleGenerativeAI

from app import supabase_client
from app.build.templates import spec, target_words, tone_hint
from app.config import settings
from app.models import BuildRequest
from app.rag.embeddings import embed_query
from app.rag.prompts import format_asset_chunks
from app.rag.vector_store import search_assets

log = logging.getLogger(__name__)

# Per-section retrieval cap.
SECTION_CHUNK_LIMIT = 6


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _llm(temp: float = 0.5, max_out: int = 1024) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.google_api_key,
        temperature=temp,
        max_output_tokens=max_out,
    )


def _llm_lite(temp: float = 0.3) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.gemini_classifier_model,
        google_api_key=settings.google_api_key,
        temperature=temp,
        max_output_tokens=512,
    )


# ---------------------------------------------------------------------------
# Stage 1: outline
# ---------------------------------------------------------------------------

OUTLINE_SYSTEM = """You are planning the structure of a piece of content.
Output: 5-7 short bullets, one per section. Each bullet is ONE LINE describing
what that section covers and which asset(s) it leans on.

Do not write the piece itself yet. Do not number the bullets. Each bullet
starts with "-". Be specific. Bullets like "Introduction" are useless.

NEVER use em-dashes or en-dashes anywhere. Use commas or periods.

Example for a blog post comparing two AI launches:
- The hook: GPT-5 dropped on Tuesday and Claude 4.7 launched the same day [asset:1] [asset:3]
- Why the timing matters for the developer market [asset:2]
- Side-by-side: pricing, context length, and the one benchmark that flipped [asset:1] [asset:3]
- What devs are actually saying in the threads [asset:4]
- The call: who should switch and who should wait
"""


async def _stage_outline(req: BuildRequest, assets: list[dict], recent_chat: str) -> list[str]:
    output_spec = spec(req.output_type)
    target = target_words(req.output_type, req.length)

    asset_list = "\n".join(
        f"  [asset:{i+1}] [{a.get('type')}] {a.get('title','')[:160]} — {(a.get('summary') or '')[:160]}"
        for i, a in enumerate(assets)
    )

    user = (
        f"OUTPUT TYPE: {output_spec['label']}\n"
        f"TARGET LENGTH: ~{target} words\n"
        f"TONE: {req.tone}  ({tone_hint(req.tone)})\n"
        f"STRUCTURE HINT: {output_spec['structure']}\n"
        f"USER INSTRUCTION: {req.instruction or '(none — use the assets)'}\n\n"
        f"ASSETS AVAILABLE:\n{asset_list}\n\n"
    )
    if recent_chat:
        user += f"RECENT CHAT CONTEXT (use as steering, not as content):\n{recent_chat}\n\n"

    user += "Produce the outline now."

    msg = await asyncio.to_thread(
        _llm(temp=0.4, max_out=512).invoke,
        [("system", OUTLINE_SYSTEM), ("human", user)],
    )
    raw = (getattr(msg, "content", "") or "").strip()
    bullets = [
        line.strip().lstrip("-•*").strip()
        for line in raw.splitlines()
        if line.strip().startswith(("-", "•", "*"))
    ]
    if not bullets:
        bullets = [line.strip() for line in raw.splitlines() if line.strip()]
    return bullets[:7]


# ---------------------------------------------------------------------------
# Stage 2: expand each bullet
# ---------------------------------------------------------------------------

EXPAND_SYSTEM = """You are writing one section of a piece. You receive:
  - the section bullet (what to cover)
  - retrieved chunks from the assets (cite as [asset:N] inline)
  - the surrounding output spec (type, tone, target length)

Write ONE section of prose. No headers, no preamble. Embed citations naturally.
Use specific quotes, numbers, and names from the chunks. That's why they're
provided. If a quote nails it, USE the quote in quotation marks and cite it.

STRICT: never use em-dashes (—) or en-dashes (–). Use commas or periods instead.

Length: aim for ~{section_words} words for THIS section.
Style: {tone_hint}. {format_rules}"""


async def _stage_expand(
    req: BuildRequest,
    assets: list[dict],
    bullets: list[str],
) -> list[str]:
    asset_ids = [a["id"] for a in assets]
    asset_index = {a["id"]: i + 1 for i, a in enumerate(assets)}
    output_spec = spec(req.output_type)
    total_target = target_words(req.output_type, req.length)
    per_section = max(int(total_target / max(len(bullets), 1)), 60)

    async def _expand_one(bullet: str) -> str:
        qvec = await asyncio.to_thread(embed_query, bullet)
        # Retrieve across all asset chunks (article_body + transcript + comment).
        tasks = [
            asyncio.to_thread(search_assets, asset_ids, qvec, kind="article_body", limit=SECTION_CHUNK_LIMIT),
            asyncio.to_thread(search_assets, asset_ids, qvec, kind="transcript", limit=SECTION_CHUNK_LIMIT),
            asyncio.to_thread(search_assets, asset_ids, qvec, kind="comment", limit=2),
        ]
        results = await asyncio.gather(*tasks)
        chunks = results[0] + results[1] + results[2]
        chunks.sort(key=lambda c: c.get("score") or 0, reverse=True)
        chunks = chunks[:SECTION_CHUNK_LIMIT]
        context = format_asset_chunks(chunks, asset_index)

        system = EXPAND_SYSTEM.format(
            section_words=per_section,
            tone_hint=tone_hint(req.tone),
            format_rules=output_spec["format_rules"],
        )
        human = (
            f"SECTION BULLET: {bullet}\n\n"
            f"RETRIEVED CHUNKS:\n{context}\n\n"
            f"Now write this section as prose."
        )

        msg = await asyncio.to_thread(
            _llm(temp=0.6, max_out=min(900, per_section * 4)).invoke,
            [("system", system), ("human", human)],
        )
        return (getattr(msg, "content", "") or "").strip()

    sections = await asyncio.gather(*(_expand_one(b) for b in bullets))
    return [s for s in sections if s]


# ---------------------------------------------------------------------------
# Stage 3: polish (streamed)
# ---------------------------------------------------------------------------

POLISH_SYSTEM = """You are the final editor. Take the joined draft below and
rewrite it for a human voice. The piece must read like it was written by a
sharp human professional, not an AI.

STRICT FORMATTING RULE:
- NEVER use em-dashes (—) or en-dashes (–). They are a dead giveaway of AI text.
- Use commas, periods, semicolons, or parentheses. Or break into two sentences.
- If you need a range (numbers), use a hyphen-minus: "5-10 minutes".

ANTI-AI checklist, apply ruthlessly:
- Cut hedges: "may", "could be argued", "it is important to note", "in conclusion",
  "in today's fast-paced world", "as we move forward", "delve into", "navigate".
- Vary sentence length. Mix 3-word punches with 25-word complex sentences.
- Use specific numbers, names, and quotes from the draft. Don't paraphrase them away.
- Convert bullet-lists-to-prose where prose flows better. Keep lists only when the
  user will scan (e.g., real comparison tables).
- Kill clichés. Replace generic intros ("In today's world…") with a concrete fact or scene.
- Preserve every [asset:N] citation that was in the draft. Do not add new ones.
- Preserve the output structure called for by the spec.

KEEP:
- The voice/tone: {tone_label} ({tone_hint})
- The format rules: {format_rules}
- The structure: {structure}
- Target length: ~{target_words} words.
- {extra_anti_ai}

OUTPUT: the polished piece in plain markdown (the frontend renders markdown).
NO preamble, NO meta-comment. Just the piece.
"""


async def polish_and_stream(
    req: BuildRequest,
    assets: list[dict],
    bullets: list[str],
    sections: list[str],
) -> AsyncIterator[str]:
    """Streaming generator: yields token strings as Gemini writes the final draft."""
    output_spec = spec(req.output_type)
    target = target_words(req.output_type, req.length)

    draft = "\n\n".join(sections)
    if not draft.strip():
        yield "[Could not generate sections — please add more relevant assets and try again.]"
        return

    system = POLISH_SYSTEM.format(
        tone_label=req.tone,
        tone_hint=tone_hint(req.tone),
        format_rules=output_spec["format_rules"],
        structure=output_spec["structure"],
        target_words=target,
        extra_anti_ai=output_spec["extra_anti_ai"],
    )
    human = (
        f"OUTPUT TYPE: {output_spec['label']}\n"
        f"USER INSTRUCTION (if any): {req.instruction or '(none)'}\n\n"
        f"DRAFT TO POLISH:\n{draft}\n\n"
        f"Polish it now."
    )

    llm = _llm(temp=0.5, max_out=4096)
    async for chunk in llm.astream([("system", system), ("human", human)]):
        content = getattr(chunk, "content", None) or ""
        if isinstance(content, list):
            content = "".join(
                p.get("text", "") if isinstance(p, dict) else str(p) for p in content
            )
        if content:
            yield content


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def collect_recent_chat(session_id: str, n_turns: int) -> str:
    if not supabase_client.is_configured() or n_turns <= 0:
        return ""
    try:
        msgs = await supabase_client.list_chat_messages(session_id)
    except Exception:
        return ""
    if not msgs:
        return ""
    tail = msgs[-(n_turns * 2):]
    lines = []
    for m in tail:
        role = m.get("role")
        content = (m.get("content") or "").strip().replace("\n", " ")
        if not content:
            continue
        prefix = "USER" if role == "user" else "ASSISTANT"
        lines.append(f"{prefix}: {content[:400]}")
    return "\n".join(lines)


async def run_build(req: BuildRequest, assets: list[dict]) -> AsyncIterator[dict]:
    """End-to-end build pipeline. Yields dict events the SSE route forwards.

    Events:
      {"stage": "outline", "bullets": [...]}
      {"stage": "expand", "section_count": N}
      {"stage": "polish_token", "text": "..."}      (many of these)
      {"stage": "done"}
    """
    recent_chat = await collect_recent_chat(req.session_id, req.chat_context_turns)

    bullets = await _stage_outline(req, assets, recent_chat)
    yield {"stage": "outline", "bullets": bullets}

    sections = await _stage_expand(req, assets, bullets)
    yield {"stage": "expand", "section_count": len(sections)}

    async for token in polish_and_stream(req, assets, bullets, sections):
        yield {"stage": "polish_token", "text": token}

    yield {"stage": "done"}
