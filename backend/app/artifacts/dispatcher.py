"""Chat → artifact intent classification.

One Gemini Flash-Lite call (cheap, ~300ms) that decides if a user message
should spawn a typed artifact or just get a normal chat reply.

Returns a `DispatchResult` with:
  - intent: "chat" | "compare" | "draft" | "summary" | "metrics" | "quotes"
  - asset_ids:  which assets the artifact should use (subset of session)
  - output_type / tone / length / instruction: for draft intents
  - reasoning: short reason string, surfaced to the user as a 1-line prefix
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings

log = logging.getLogger(__name__)


# What the model is allowed to return.
INTENTS = ("chat", "compare", "draft", "summary", "metrics", "quotes")
OUTPUT_TYPES = ("blog_post", "video_script", "x_thread", "linkedin_post", "newsletter")
TONES = ("confident", "analytical", "casual", "irreverent")
LENGTHS = ("short", "medium", "long")


@dataclass
class ClarificationOption:
    id: str
    label: str
    description: str = ""


@dataclass
class Clarification:
    """Structured follow-up question to ask before generating the artifact.

    kind:
      mcq_single — pick exactly 1
      mcq_multi  — pick N from a list (min_picks / max_picks)
      text       — free text response
    """
    kind: str                              # "mcq_single" | "mcq_multi" | "text"
    question: str
    options: list[ClarificationOption] = field(default_factory=list)
    min_picks: int = 1
    max_picks: int = 1
    intent_hint: str = ""                  # which artifact this is gating

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "question": self.question,
            "options": [{"id": o.id, "label": o.label, "description": o.description} for o in self.options],
            "min_picks": self.min_picks,
            "max_picks": self.max_picks,
            "intent_hint": self.intent_hint,
        }


@dataclass
class DispatchResult:
    intent: str = "chat"
    asset_ids: list[str] = field(default_factory=list)
    output_type: Optional[str] = None
    tone: Optional[str] = None
    length: Optional[str] = None
    instruction: str = ""
    reasoning: str = ""
    clarification: Optional[Clarification] = None

    @property
    def is_artifact(self) -> bool:
        return self.intent != "chat" and self.clarification is None

    @property
    def needs_clarification(self) -> bool:
        return self.clarification is not None


_SYSTEM = """You route a content-creator's chat message to the right tool.

You're given:
  - the user's message
  - a list of saved ASSETS in the session, with their numeric index, type, and short title

Return ONE JSON object with these keys:
  intent       — one of: "chat", "compare", "draft", "summary", "metrics", "quotes"
  asset_ids    — array of asset INDEX numbers (1-based, NOT UUIDs) the artifact should use
  output_type  — if intent=draft: one of "blog_post" | "video_script" | "x_thread" | "linkedin_post" | "newsletter"
  tone         — if intent=draft: "confident" | "analytical" | "casual" | "irreverent"
  length       — if intent=draft: "short" | "medium" | "long"
  instruction  — short extra steering ("focus on X", "make it sharper"), can be ""
  reasoning    — 1 short sentence on why this intent

How to choose intent:
  "compare"   → user wants a side-by-side analysis of TWO assets (videos preferred).
                Phrases: "compare", "vs", "which is better", "A vs B", "side by side".
                MUST pick exactly 2 asset_ids.
  "draft"     → user wants you to PRODUCE a finished piece (blog post, tweet thread,
                video script, LinkedIn post, newsletter). Phrases: "write", "draft",
                "generate", "make me a", "compose".
                Pick any number of asset_ids (default: all of them).
  "summary"   → user wants a concise summary brief of one or more assets.
                Phrases: "summarize", "tldr", "brief me", "what are these saying".
  "metrics"   → user wants engagement / sentiment / view metrics broken out.
                Phrases: "engagement", "sentiment", "performance", "metrics", "stats".
  "quotes"    → user wants the best quotes / lines / comments pulled out.
                Phrases: "best quotes", "key lines", "comments", "what people said".
  "chat"      → DEFAULT. Anything else — questions, follow-ups, clarifications.
                If you're unsure, pick chat.

Pick output_type smartly based on what they asked for. Default tone=confident, length=medium.

Output STRICT JSON only. No markdown, no prose, no code fences. Just the object."""


def _assets_block(assets: list[dict]) -> str:
    if not assets:
        return "(no assets saved yet)"
    lines = []
    for i, a in enumerate(assets):
        title = (a.get("title") or "Untitled")[:120]
        lines.append(f"  [{i+1}] [{a.get('type','?')}] {title}")
    return "\n".join(lines)


def _coerce_asset_ids(raw, n_assets: int, all_asset_ids: list[str]) -> list[str]:
    """Map the model's 1-based indices to real UUIDs. Clamps to valid range."""
    if not raw:
        return []
    out = []
    seen = set()
    for v in raw:
        try:
            idx = int(v) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= idx < n_assets and all_asset_ids[idx] not in seen:
            out.append(all_asset_ids[idx])
            seen.add(all_asset_ids[idx])
    return out


def _parse_json_lenient(text: str) -> Optional[dict]:
    """Pull a JSON object out of model output even if it's wrapped in fences."""
    if not text:
        return None
    text = text.strip()
    # Strip ```json or ``` fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Sometimes the model adds trailing commentary. Grab the first {...} block.
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


_ARTIFACT_TRIGGERS = (
    "compare", "draft", "write", "generate", "make me", "build a", "build me",
    "create a", "create me", "summarize", "summary", "tldr", "brief",
    "engagement", "sentiment", "performance", "metrics", "stats",
    "quote", "best lines", "best line", "best comments",
    " vs ", " vs.", "versus", "side by side", "side-by-side", "against",
    "blog", "thread", "linkedin", "newsletter", "script", "tweet",
    # Single-word MCQ answers (clarification follow-ups)
    "blog post", "video script", "x thread", "linkedin post",
    "confident", "analytical", "casual", "irreverent",
)


def _has_artifact_trigger(message: str, recent_messages: list[str]) -> bool:
    """Cheap keyword check across the latest message + recent context."""
    haystack = (message + " " + " ".join(recent_messages[-3:])).lower()
    return any(t in haystack for t in _ARTIFACT_TRIGGERS)


def classify_intent(
    message: str,
    assets: list[dict],
    recent_messages: Optional[list[str]] = None,
) -> DispatchResult:
    """Synchronous classify. Safe to call from inside async code via to_thread.

    `recent_messages` is a chronological list of the last few USER turns
    (excluding the current one). The dispatcher uses these to understand
    follow-up answers, e.g. "Confident" alone is meaningless, but in the
    context of "draft something" -> "Blog post" -> "Confident" the model
    correctly connects them.

    Fast path: if neither the current message nor recent turns contain ANY
    artifact-trigger word, skip the Gemini-Lite call entirely and treat as
    chat. Saves ~500-1000ms per turn on normal conversation.
    """
    if not message.strip():
        return DispatchResult(intent="chat", reasoning="empty message")

    recent_messages = recent_messages or []

    # Fast path: obviously chat, no LLM needed.
    if not _has_artifact_trigger(message, recent_messages):
        return DispatchResult(
            intent="chat",
            reasoning="no artifact triggers in message or recent context",
        )

    # Stitch the accumulated context so single-word MCQ answers retain meaning.
    effective_message = _stitch_with_context(message, recent_messages)

    assets_block = _assets_block(assets)
    history_block = ""
    if recent_messages:
        recent_lines = "\n".join(f"  - {m}" for m in recent_messages[-4:])
        history_block = f"\nRECENT USER MESSAGES (for context):\n{recent_lines}\n"
    user = (
        f"USER MESSAGE (latest): {message}"
        + (f"\nCOMBINED INTENT: {effective_message}" if effective_message != message else "")
        + history_block
        + f"\nSESSION ASSETS:\n{assets_block}"
    )

    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_classifier_model,
        google_api_key=settings.google_api_key,
        temperature=0.0,
        max_output_tokens=256,
    )

    try:
        msg = llm.invoke([("system", _SYSTEM), ("human", user)])
        raw = getattr(msg, "content", "") or ""
        if isinstance(raw, list):
            raw = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in raw)
    except Exception as e:
        log.warning("dispatcher LLM call failed: %s", e)
        return DispatchResult(intent="chat", reasoning="classifier failed; defaulting to chat")

    data = _parse_json_lenient(raw)
    if not data or not isinstance(data, dict):
        log.warning("dispatcher returned non-JSON: %r", raw[:200])
        return DispatchResult(intent="chat", reasoning="unparseable classifier output")

    intent = data.get("intent")
    if intent not in INTENTS:
        intent = "chat"

    all_ids = [a["id"] for a in assets]
    asset_ids = _coerce_asset_ids(data.get("asset_ids"), len(assets), all_ids)

    output_type = data.get("output_type")
    if output_type not in OUTPUT_TYPES:
        output_type = None
    tone = data.get("tone") if data.get("tone") in TONES else None
    length = data.get("length") if data.get("length") in LENGTHS else None

    clarification: Optional[Clarification] = None

    # Defensive rules — also build clarifications where ambiguity is high.
    if intent == "compare":
        video_assets = [a for a in assets if a.get("type") == "video"]
        if len(video_assets) < 2:
            log.info("compare intent but only %d video assets", len(video_assets))
            intent = "chat"
        elif len(video_assets) == 2:
            # Exactly two — no ambiguity, use them.
            asset_ids = [a["id"] for a in video_assets]
        elif _user_named_specific_videos(message, video_assets) and len(asset_ids) == 2:
            # User explicitly named the two videos, trust the LLM's pick.
            pass
        else:
            # >2 candidates and user didn't name specifics → ask.
            clarification = Clarification(
                kind="mcq_multi",
                question="Which two videos should I compare?",
                options=[
                    ClarificationOption(
                        id=a["id"],
                        label=(a.get("title") or "Untitled")[:80],
                        description=_describe_video(a),
                    )
                    for a in video_assets
                ],
                min_picks=2,
                max_picks=2,
                intent_hint="compare",
            )

    elif intent == "draft":
        if not asset_ids:
            asset_ids = all_ids
        # Two-step clarification — always ASKS once before drafting:
        #   1. If the user (across recent turns combined) didn't name an
        #      output type, ask which.
        #   2. Once they have, if no tone, ask tone.
        # We check the effective message (current + recent stitched) so
        # answers like "Confident" don't lose the "Blog post" context.
        if not _user_specified_output_type(effective_message):
            clarification = Clarification(
                kind="mcq_single",
                question="What kind of piece should I draft?",
                options=[
                    ClarificationOption(id="blog_post", label="Blog post",
                                         description="800-1500 words, sectioned"),
                    ClarificationOption(id="video_script", label="Video script",
                                         description="90-180 sec, spoken cadence"),
                    ClarificationOption(id="x_thread", label="X / Twitter thread",
                                         description="6-10 tweets, hook + body + CTA"),
                    ClarificationOption(id="linkedin_post", label="LinkedIn post",
                                         description="200-400 words, professional"),
                    ClarificationOption(id="newsletter", label="Newsletter",
                                         description="400-700 words, conversational"),
                ],
                min_picks=1, max_picks=1,
                intent_hint="draft",
            )
        elif not _user_specified_tone(effective_message):
            # They picked an output type. Now lock in tone before generating.
            if not output_type:
                output_type = _infer_output_type(effective_message) or "blog_post"
            clarification = Clarification(
                kind="mcq_single",
                question="What tone should I write in?",
                options=[
                    ClarificationOption(id="confident", label="Confident",
                                         description="Declarative, no hedging"),
                    ClarificationOption(id="analytical", label="Analytical",
                                         description="Evidence-led, careful"),
                    ClarificationOption(id="casual", label="Casual",
                                         description="Friendly, like texting"),
                    ClarificationOption(id="irreverent", label="Irreverent",
                                         description="Sharp, willing to call out clichés"),
                ],
                min_picks=1, max_picks=1,
                intent_hint="draft",
            )
        else:
            if not output_type:
                output_type = _infer_output_type(effective_message) or "blog_post"
            if not tone:
                tone = _infer_tone(effective_message) or "confident"
            if not length:
                length = "medium"

    elif intent in ("summary", "metrics", "quotes"):
        if not asset_ids:
            asset_ids = all_ids

    return DispatchResult(
        intent=intent,
        asset_ids=asset_ids,
        output_type=output_type,
        tone=tone,
        length=length,
        instruction=(data.get("instruction") or "")[:500],
        reasoning=(data.get("reasoning") or "")[:240],
        clarification=clarification,
    )


def _describe_video(asset: dict) -> str:
    """Short subtitle for the MCQ option — creator + view count."""
    meta = asset.get("metadata_json") or {}
    creator = meta.get("creator") or ""
    views = meta.get("views")
    bits = []
    if creator:
        bits.append(f"@{creator}")
    if isinstance(views, (int, float)) and views:
        bits.append(f"{int(views):,} views")
    return " · ".join(bits)


_OUTPUT_TYPE_HINTS = {
    "blog_post":      ("blog",),
    "x_thread":       ("tweet", "thread", "x post", "twitter"),
    "linkedin_post":  ("linkedin",),
    "newsletter":     ("newsletter",),
    "video_script":   ("script", "video script"),
}

_TONE_HINTS = {
    "confident": ("confident",),
    "analytical": ("analytical", "investigative"),
    "casual": ("casual", "conversational", "friendly"),
    "irreverent": ("irreverent", "punchy", "snarky"),
}


def _user_specified_output_type(message: str) -> bool:
    """True if the user's literal message names an output medium.

    We don't include the bare word "post" because it's too common ("draft a
    post"). Specific media words only.
    """
    ml = message.lower()
    return any(h in ml for hints in _OUTPUT_TYPE_HINTS.values() for h in hints)


def _infer_output_type(message: str) -> Optional[str]:
    ml = message.lower()
    for k, hints in _OUTPUT_TYPE_HINTS.items():
        if any(h in ml for h in hints):
            return k
    return None


def _user_specified_tone(message: str) -> bool:
    ml = message.lower()
    return any(h in ml for hints in _TONE_HINTS.values() for h in hints)


def _infer_tone(message: str) -> Optional[str]:
    ml = message.lower()
    for k, hints in _TONE_HINTS.items():
        if any(h in ml for h in hints):
            return k
    return None


def _stitch_with_context(message: str, recent_messages: list[str]) -> str:
    """Concat the current message with the last few user turns so keyword
    checks (output type, tone) can still match when the user is answering
    a clarification with a short label.

    e.g. recent=["draft something", "write a Blog post"], current="Confident"
         → "draft something. write a Blog post. Confident"

    Order doesn't matter for keyword detection. We cap context to avoid
    over-stitching unrelated old turns.
    """
    if not recent_messages:
        return message
    tail = [m.strip() for m in recent_messages[-3:] if m and m.strip()]
    if not tail:
        return message
    return ". ".join([*tail, message.strip()])


def _user_named_specific_videos(message: str, videos: list[dict]) -> bool:
    """True if the user's literal message mentions any video by title word.

    We pick the first 'distinctive' word of each title (longer than 4 chars,
    not stopword-y) and check if at least one appears in the user message.
    Catches "compare the iPhone video and the Pixel video" without needing
    full title matching.
    """
    if not videos:
        return False
    ml = message.lower()
    for v in videos:
        title = (v.get("title") or "").lower()
        for word in title.split():
            word = "".join(c for c in word if c.isalnum())
            if len(word) >= 5 and word in ml:
                return True
    return False
