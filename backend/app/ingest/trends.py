"""Topic trend status via Google Trends (pytrends).

Two-step pipeline:
  1. Gemini extracts 3-5 topic keywords from the transcript
  2. pytrends pulls 90-day search interest, classify rising/steady/declining/niche

pytrends is unofficial and rate-limits aggressively. We swallow ALL errors
and return "unavailable" rather than failing the ingest. The system prompt
tells the LLM to caveat the trend status appropriately.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import settings
from app.models import TrendStatus

log = logging.getLogger(__name__)

_KEYWORDS_PROMPT = """Extract 3 to 5 short topic keywords from this video transcript.
Pick keywords a person might TYPE INTO GOOGLE to search for similar content.
Avoid generic words ("video", "watching"). Prefer 1-2 word phrases over sentences.

Return STRICT JSON only: {{"keywords": ["...", "..."]}}

Transcript (truncated):
{transcript}
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_keywords(transcript_text: str) -> list[str]:
    """One Gemini call -> 3-5 keyword strings. [] on failure."""
    if not settings.google_api_key:
        log.warning("GOOGLE_API_KEY not set; skipping topic-keyword extraction")
        return []
    if not transcript_text.strip():
        return []

    # Lazy import: langchain-google-genai is heavy (pulls torch-adjacent
    # protobuf code) and we want it absent at module import to keep the
    # cold-start hot path lean. We call via the LangChain wrapper rather
    # than the legacy `google.generativeai` SDK because the latter pins an
    # older google-ai-generativelanguage that conflicts with our pinned
    # langchain-google-genai >= 2.1.
    from langchain_google_genai import ChatGoogleGenerativeAI

    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_classifier_model,
        google_api_key=settings.google_api_key,
        temperature=0.0,
        max_output_tokens=4096,
        # JSON mode -- forces the model to return strict JSON.
        model_kwargs={
            "generation_config": {"response_mime_type": "application/json"},
        },
    )

    snippet = transcript_text[:4000]
    try:
        resp = llm.invoke(_KEYWORDS_PROMPT.format(transcript=snippet))
        content = resp.content
        if isinstance(content, list):
            content = "".join(
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in content
            )
        text = (content or "").strip()
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini keyword extraction failed: %s", e)
        return []

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_RE.search(text)
        if not m:
            log.warning("Keyword extraction returned no JSON: %s", text[:200])
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    try:
        kws = data.get("keywords") or []
        return [str(k).strip() for k in kws if isinstance(k, str) and k.strip()][:5]
    except (TypeError, ValueError):
        return []


def _classify_trend(values: list[float]) -> TrendStatus:
    """Heuristic on a 90-point search-interest series (0..100 each)."""
    if len(values) < 12:
        return "unavailable"
    avg = sum(values) / len(values)
    if avg < 3.0:
        return "niche"
    cut = int(len(values) * 2 / 3)  # last third vs first two-thirds
    earlier = values[:cut]
    recent = values[cut:]
    if not earlier or not recent:
        return "unavailable"
    earlier_avg = sum(earlier) / len(earlier)
    recent_avg = sum(recent) / len(recent)
    if earlier_avg < 1.0:  # near-zero base, ratio noise
        return "niche"
    ratio = recent_avg / earlier_avg
    if ratio > 1.3:
        return "rising"
    if ratio < 0.7:
        return "declining"
    return "steady"


def _patch_urllib3_retry_for_pytrends() -> None:
    """pytrends 4.9.2 passes `method_whitelist` to urllib3's Retry, but
    urllib3 2.x renamed that param to `allowed_methods`. Translate on the
    fly so pytrends keeps working until it gets an upstream fix.
    """
    try:
        from urllib3.util.retry import Retry  # type: ignore
    except ImportError:
        return
    if getattr(Retry, "_method_whitelist_patched", False):
        return
    orig_init = Retry.__init__

    def patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if "method_whitelist" in kwargs and "allowed_methods" not in kwargs:
            kwargs["allowed_methods"] = kwargs.pop("method_whitelist")
        orig_init(self, *args, **kwargs)

    Retry.__init__ = patched_init  # type: ignore[method-assign]
    Retry._method_whitelist_patched = True  # type: ignore[attr-defined]


def topic_trend_status(keywords: list[str]) -> TrendStatus:
    """pytrends call wrapped in best-effort error handling."""
    if not keywords:
        return "unavailable"
    try:
        _patch_urllib3_retry_for_pytrends()
        # Lazy import: pytrends is heavy and we want it absent to be fine.
        from pytrends.request import TrendReq

        pytrends = TrendReq(hl="en-US", tz=0, timeout=(5, 15), retries=1, backoff_factor=0.3)
        # pytrends limits batch to 5 keywords
        pytrends.build_payload(keywords[:5], timeframe="today 3-m")
        df = pytrends.interest_over_time()
        if df is None or df.empty:
            return "unavailable"
        # Drop the auto-added isPartial column
        cols = [c for c in df.columns if c != "isPartial"]
        if not cols:
            return "unavailable"
        # Average across keywords at each timestamp -> single series
        series = df[cols].mean(axis=1).tolist()
        return _classify_trend(series)
    except Exception as e:  # noqa: BLE001
        log.warning("pytrends call failed: %s", e)
        return "unavailable"
