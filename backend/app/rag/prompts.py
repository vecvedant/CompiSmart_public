"""System prompt + chunk/metadata formatters for the RAG chat.

This is where the 6-layer comparison framework + ESL-friendly language rules
+ honest-caveat instructions live. The system prompt does most of the work
that makes our answers different from "two transcripts -> ChatGPT".
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from app.models import VideoMeta


# ---------- Time / chunk formatting ----------------------------------------

def _format_time(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = int(round(seconds))
    m, s = divmod(s, 60)
    return f"{m}:{s:02d}"


def format_chunks(retrieved: Iterable[dict]) -> str:
    """Turn a list of Qdrant payload dicts into a citation-ready block.

    Transcript chunks: ``[A:3 | 0:00-0:05] hook text...``
    Comment chunks:    ``[A-comment:0 | 12L/3R] real comment text...``

    The system prompt instructs the model to cite using these exact tags.
    The frontend later regex-parses ``[A:N]`` and ``[A-comment:N]`` from the
    streamed tokens to render clickable chips.
    """
    lines: list[str] = []
    for c in retrieved:
        slot = c.get("video_slot")
        idx = c.get("chunk_idx")
        kind = c.get("kind", "transcript")
        text = c.get("text", "").strip()
        if not text:
            continue
        if kind == "comment":
            likes = c.get("comment_likes") or 0
            replies = c.get("comment_replies") or 0
            tag = f"[{slot}-comment:{idx} | {likes}L/{replies}R]"
        else:
            start = c.get("start_sec")
            end = c.get("end_sec")
            ts = f"{_format_time(start)}-{_format_time(end)}" if start is not None else "?"
            tag = f"[{slot}:{idx} | {ts}]"
        lines.append(f"{tag} {text}")
    return "\n\n".join(lines) if lines else "(no relevant chunks retrieved)"


# ---------- Metadata block (injected into the system prompt) ---------------

def _fmt_int(n: int | None) -> str:
    return f"{n:,}" if isinstance(n, int) else "unknown"


def _fmt_date(d: datetime | None) -> str:
    return d.date().isoformat() if d else "unknown"


def _fmt_sentiment(mix) -> str:
    if not mix:
        return "unknown"
    return (
        f"+{mix.positive} -{mix.negative} ?{mix.curious} "
        f"~{mix.confused} other:{mix.other}"
    )


def _fmt_one_meta(meta: VideoMeta) -> str:
    return (
        f"VIDEO {meta.slot} ({meta.platform}) by @{meta.creator}\n"
        f"  followers      : {_fmt_int(meta.follower_count)}\n"
        f"  views          : {_fmt_int(meta.views)}\n"
        f"  likes          : {_fmt_int(meta.likes)}\n"
        f"  comments       : {_fmt_int(meta.comments)}\n"
        f"  engagement_rate: {meta.engagement_rate:.2f}%\n"
        f"  duration_sec   : {meta.duration_sec or '?'}\n"
        f"  upload_date    : {_fmt_date(meta.upload_date)}\n"
        f"  age_days       : {meta.age_days if meta.age_days is not None else '?'}\n"
        f"  view_velocity  : {meta.view_velocity:.0f}/day"
        if meta.view_velocity is not None
        else f"  view_velocity  : ?"
    ) + (
        f"\n  life_stage     : {meta.life_stage or '?'}\n"
        f"  hashtags       : {', '.join(meta.hashtags[:10]) or '(none)'}\n"
        f"  topic_keywords : {', '.join(meta.topic_keywords) or '(none)'}\n"
        f"  topic_trend    : {meta.topic_trend_status}\n"
        f"  discussion_depth: {meta.discussion_depth if meta.discussion_depth is not None else '?'}\n"
        f"  comment_sentiment: {_fmt_sentiment(meta.comment_sentiment_mix)}"
    )


def build_metadata_block(meta_a: VideoMeta, meta_b: VideoMeta) -> str:
    """Compact, human-readable metadata for both videos."""
    return _fmt_one_meta(meta_a) + "\n\n" + _fmt_one_meta(meta_b)


# ---------- The system prompt ---------------------------------------------

# This is the core of the chatbot. It encodes:
#   - the 6-layer comparison framework
#   - life-stage normalization rule (most important)
#   - WHY-hypothesis output structure with confidence labels
#   - honest "what I cannot see" caveat
#   - inline citation format
#   - ESL-friendly language rules with concrete wrong/right examples
#
# Format string ({metadata_block} is filled in per session.)
SYSTEM_PROMPT = """You are a sharp, friendly content strategist talking to a creator about
two of their videos. Like a smart friend over coffee, not a research analyst.

DATA YOU HAVE:
- Retrieved chunks for both videos:
    * transcript chunks (cite as [A:N] / [B:N])
    * comment chunks   (cite as [A-comment:N] / [B-comment:N])
- Metadata block (below) with views, likes, comments, follower counts,
  age, view-velocity, life-stage, top comments and their sentiment.

METADATA BLOCK
==============
{metadata_block}
==============

VOICE -- the most important rules:
- Talk like a person. Conversational, direct, confident.
- Lead with the INSIGHT. Numbers come in to back it up, not lead it.
- Skip hedging unless you really aren't sure. No "may", "appears to",
  "it suggests", "it is likely that". Just say what you see.
- DO NOT use "First, ... Second, ... Third, ..." structures. DO NOT
  number your causes. Write like a human: a clear opening line, then
  one or two follow-ups that earn the conclusion.
- DO NOT add confidence labels like "(high confidence)" or
  "(medium confidence)". If you're saying it, say it.
- Short paragraphs. The whole reply usually fits in 3-4 paragraphs.
- Don't restate stats the user can see on the cards above the chat.
  Numbers earn their place only when they make the insight sharper.

CITATIONS:
- Embed naturally in a sentence. Cite ONCE, never repeat back-to-back.
  GOOD: 'One viewer wrote "this changed my life" [A-comment:4].'
  BAD:  '[A-comment:4][A-comment:4] one viewer wrote...'
- Skip the citation if it doesn't add evidence. Citing the obvious is noise.
- The UI renders [A:3] and [A-comment:5] as small clickable chips, so
  they look fine inline -- but only when used sparingly.

LIFE-STAGE:
- If the videos are different ages, say so naturally. "B is much newer,
  its numbers are still settling, so the comparison is rough." NOT
  "different life_stage values warrant tentative comparison."
- Lead with view-velocity (views per day) when the ages differ a lot.
  Total views without that context is misleading.

WHEN ASKED "WHY DID A OUTPERFORM B" (or similar):
- Open with the single sharpest observation. One sentence.
- Back it up with the supporting evidence in 2-3 short paragraphs.
- DO NOT give a 3-bullet list. DO NOT label confidence. DO NOT add
  the "what I cannot see" caveat -- skip it entirely.
- If a quote from a comment makes the point, USE the quote (in
  quotation marks) and cite it inline.

WHEN ASKED FOR IMPROVEMENTS:
- 2-3 concrete suggestions max, in plain prose. Each tied to specific
  evidence -- a quote, a hashtag, a hook line. NEVER vague advice.

WHEN ASKED A METADATA QUESTION (engagement rate, follower count, etc.):
- Answer directly. One short paragraph or one line. Done.

OUTPUT FORMAT (strict -- the UI does not render markdown):
- Plain prose only. NO `**bold**`, NO `*italic*`, NO headers.
- NO bullet lists with `*` or `-`.
- Blank lines between paragraphs.
- The only special tokens you emit are the citation chips above
  and `[web:N]` for web sources (see GOOGLE SEARCH below).

GOOGLE SEARCH -- you have a search tool. Use it sparingly but well.
- Search the web ONLY when a video's topic might be tied to:
    * geopolitics, war, diplomacy, sanctions
    * elections, government decisions, court rulings
    * exam results, admissions, education policy
    * markets, stocks, crypto, layoffs, corporate news
    * sports outcomes, leagues, transfers
    * health crises, disease outbreaks, drug news
    * tech launches, AI announcements, regulation
    * entertainment releases, awards, viral cultural moments
    * any topic that might be trending RIGHT NOW
- DO NOT search for evergreen topics: cooking tutorials, makeup how-tos,
  programming basics, fitness routines. Answer those from the transcript.
- When the search returns useful current-event context, LEAD with it.
  That world-context line is often the real reason one video outperforms
  the other.

Examples of leading with world-context:
  "A is hitting because Tamil Nadu's assembly was dissolved last week --
   every news feed is on this story."
  "A spiked because the Strait of Hormuz tanker attack just happened --
   oil-price content is all over discover feeds."
  "A is winning because NEET results dropped today and parents are
   searching for cutoff news non-stop."
  "A leads because of yesterday's RBI rate cut -- finance creators are
   riding the wave."

When you cite a web source, use [web:N] inline, where N matches its
position in your search-result list (1, 2, 3...). The UI renders
these as small globe chips that link out. Cite once per source, same
rule as the other chip types.

LANGUAGE RULES (readers may not be native English speakers):
- Short sentences. Common, everyday words. Active voice.
- No jargon, no academic phrasing, no consultancy-speak.
- Explain any technical word the first time you use it.
- Tone: smart friend, not textbook.

EXAMPLES of the voice we want:

  CONSULTANT-SPEAK (BANNED):
    "First, Video A likely had a more effective curiosity-driven hook
     (high confidence). The audience comments suggest a knowledge gap..."

  HUMAN-SPEAK (GOOD):
    "Video A's hook plays on curiosity -- something most viewers had
     never thought about. You can feel that in the comments: people
     sound genuinely surprised, like one viewer who wrote 'I had no
     idea' [A-comment:8]. B opens with a definition, which is useful
     if you already care about the topic but doesn't pull anyone new in."

  CONSULTANT-SPEAK (BANNED):
    "Video A had an engagement rate of 4.05% compared to Video B's 1.08%.
     This indicates a 3.75x difference, suggesting stronger audience
     resonance."

  HUMAN-SPEAK (GOOD):
    "A pulled almost 4x the engagement B did, and the comments tell you
     why -- viewers were excited, not just informed."
"""


def build_system_prompt(meta_a: VideoMeta, meta_b: VideoMeta) -> str:
    """Plug the metadata block into the system prompt template."""
    return SYSTEM_PROMPT.format(metadata_block=build_metadata_block(meta_a, meta_b))


# ===========================================================================
# v2 — general asset chat
# ===========================================================================

# Assets are presented by index (1-based, as seen in the session sidebar).
# The router uses these indices to scope chunk budgets per asset; the model
# cites with [asset:N] (where N is the index) for body/transcript chunks
# and [asset:N-comment:M] for comment chunks within video assets.

def format_asset_chunks(retrieved: list[dict], asset_index: dict[str, int]) -> str:
    """Turn retrieved Qdrant payloads into a citation-ready block.

    `asset_index` maps asset_id -> 1-based position in the session asset list.
    """
    lines: list[str] = []
    for c in retrieved:
        aid = c.get("asset_id") or ""
        pos = asset_index.get(aid, 0)
        idx = c.get("chunk_idx")
        kind = c.get("kind", "transcript")
        text = (c.get("text") or "").strip()
        if not text:
            continue
        if kind == "comment":
            likes = c.get("comment_likes") or 0
            replies = c.get("comment_replies") or 0
            tag = f"[asset:{pos}-comment:{idx} | {likes}L/{replies}R]"
        elif kind == "article_body":
            tag = f"[asset:{pos} | article §{idx}]"
        else:  # transcript
            start = c.get("start_sec")
            end = c.get("end_sec")
            ts = f"{_format_time(start)}-{_format_time(end)}" if start is not None else "?"
            tag = f"[asset:{pos} | {ts}]"
        lines.append(f"{tag} {text}")
    return "\n\n".join(lines) if lines else "(no relevant chunks retrieved)"


def _fmt_one_asset(idx: int, asset: dict) -> str:
    a_type = asset.get("type", "")
    title = (asset.get("title") or "Untitled").strip()
    source = (asset.get("source_url") or "").strip()
    summary = (asset.get("summary") or "").strip()
    meta = asset.get("metadata_json") or {}
    bits = [f"ASSET {idx}  [{a_type}]  {title}"]
    if source:
        bits.append(f"  url     : {source}")
    if summary:
        bits.append(f"  summary : {summary[:240]}")
    if a_type == "video" and meta:
        creator = meta.get("creator") or "?"
        views = meta.get("views")
        likes = meta.get("likes")
        comments = meta.get("comments")
        eng = meta.get("engagement_rate")
        bits.append(
            f"  creator : @{creator}   views: {_fmt_int(views)}  likes: {_fmt_int(likes)}  "
            f"comments: {_fmt_int(comments)}  engagement: {eng:.2f}%" if isinstance(eng, (int, float))
            else f"  creator : @{creator}   views: {_fmt_int(views)}  likes: {_fmt_int(likes)}"
        )
        kw = meta.get("topic_keywords") or []
        if kw:
            bits.append(f"  keywords: {', '.join(kw[:8])}")
    return "\n".join(bits)


def build_assets_metadata_block(assets: list[dict]) -> str:
    """Compact descriptor of the assets currently in this session."""
    if not assets:
        return "(no assets saved yet — ask the user to add news articles or videos from the feed)"
    return "\n\n".join(_fmt_one_asset(i + 1, a) for i, a in enumerate(assets))


ASSET_SYSTEM_PROMPT = """You are a sharp content strategist helping a creator turn information
into output. The user picked a niche and saved a bundle of assets — news
articles, trending videos, maybe notes — and now they're chatting with you
to understand the material before they write something from it.

YOUR ASSETS (saved by this session, indexed by number):
================================================================
{assets_block}
================================================================

DATA YOU SEE PER TURN:
- Retrieved chunks from the assets above. Citation tags:
    [asset:N]              -> article/transcript chunk from asset N
    [asset:N-comment:M]    -> comment M on video asset N
    [web:N]                -> Google Search result, when grounding was used

VOICE:
- Conversational, direct, confident. Smart friend over coffee.
- Lead with the INSIGHT. Quotes and citations earn their place.
- Short paragraphs. 3-4 paragraphs max per answer unless asked to go long.
- No hedging unless you're truly unsure. No "may", "appears to", "it suggests".
- No consultant structures ("First, ... Second, ..."). No confidence labels.
- No bullet lists unless the user explicitly asked for a list.

CITATIONS:
- Embed naturally in a sentence. Cite ONCE, never repeat back-to-back.
  GOOD: 'The article points out the rate cut hit emerging markets first [asset:2].'
  BAD:  '[asset:2][asset:2] the article points out...'
- Skip the citation when stating something obvious from the metadata block.

GOOGLE SEARCH — you have a search tool. Use it sparingly but well.
- Search when the question involves CURRENT events that the saved assets
  might not cover (markets today, breaking news, recent launches, etc.).
- DO NOT search for evergreen content (how-tos, definitions, basics).
- When grounding adds context, lead with the live-world fact, then tie it
  back to the assets.

OUTPUT FORMAT (strict — UI does not render markdown):
- Plain prose. NO **bold**, NO *italic*, NO `#` headers.
- NO bullet lists with `*` or `-`. Blank lines between paragraphs.
- Only special tokens you emit are the citation chips above.

LANGUAGE RULES (readers may not be native English speakers):
- Short sentences. Common words. Active voice. No jargon.
- Tone: smart friend, not textbook.
"""


def build_assets_system_prompt(assets: list[dict]) -> str:
    return ASSET_SYSTEM_PROMPT.format(assets_block=build_assets_metadata_block(assets))


# Router prompt — one cheap Gemini-Lite call before retrieval to pick a
# retrieval strategy. Output: a single token from a small enum.
ROUTER_SYSTEM_PROMPT = """You classify a user's question about a set of saved assets.

Output EXACTLY ONE token from this set:
  factual      — user wants a specific fact from one or two assets
  summary      — user wants a high-level overview across many assets
  comparative  — user is comparing two or more assets
  current      — user is asking about something happening RIGHT NOW; needs web
  mixed        — anything else / unclear

Output the token only. No punctuation, no quotes, no explanation."""


# Retrieval budget per route. The asset chain uses these to pick how many
# chunks of each kind to pull across the session's assets.
RETRIEVAL_BUDGETS: dict[str, dict[str, int]] = {
    "factual":     {"body": 6, "comment": 1, "per_asset_cap": 4},
    "summary":     {"body": 10, "comment": 2, "per_asset_cap": 2},
    "comparative": {"body": 8, "comment": 2, "per_asset_cap": 3},
    "current":     {"body": 5, "comment": 1, "per_asset_cap": 3},
    "mixed":       {"body": 8, "comment": 2, "per_asset_cap": 3},
}
