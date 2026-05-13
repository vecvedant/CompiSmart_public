"""Top comments fetcher (per platform) + Gemini sentiment classifier.

YouTube:   YouTube Data API v3 commentThreads.list (primary).
           yt-dlp `getcomments=True` (fallback, broken on Cloud Run).
Instagram: Apify instagram-comments-scraper.

Both return a normalized list[Comment]. Failures here are non-fatal --
comments are an add-on, not core. We log + return [] rather than raising.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import yt_dlp

from app.config import settings
from app.ingest.apify_client import _client as _apify_client
from app.ingest.detect import detect_platform, extract_youtube_id
from app.ingest.youtube_data_api import fetch_top_comments as _yt_data_api_comments
from app.models import Comment, CommentSentimentMix

log = logging.getLogger(__name__)

TOP_N = 10  # per video

_YDL_COMMENTS_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "format": "bestaudio/best/worst",
    "ignore_no_formats_error": True,
    "getcomments": True,
    "extractor_args": {
        "youtube": {
            "comment_sort": ["top"],
            # Format: top_level_max,reply_max,reply_pages
            "max_comments": [f"{TOP_N},0,0"],
        },
    },
}

_IG_COMMENT_ACTOR = "apify/instagram-comment-scraper"


# ---------- YouTube --------------------------------------------------------


def _fetch_youtube_comments(url: str) -> list[Comment]:
    """YouTube Data API v3 commentThreads.list, with yt-dlp as fallback.

    The Data API works from Cloud Run (key-auth, no IP block). yt-dlp is
    kept for symmetry but will normally 403 in production.
    """
    # Primary: Data API
    try:
        video_id = extract_youtube_id(url)
        out = _yt_data_api_comments(video_id, max_results=TOP_N)
        if out:
            log.info("YouTube comments via Data API: %d for %s", len(out), video_id)
            return out
        log.info("YouTube Data API returned 0 comments for %s; trying yt-dlp", video_id)
    except Exception as e:  # noqa: BLE001 — try fallback
        log.warning("YouTube Data API comments failed for %s (%s); trying yt-dlp", url, e)

    # Fallback: yt-dlp (typically blocked on Cloud Run; works locally)
    try:
        with yt_dlp.YoutubeDL(_YDL_COMMENTS_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # noqa: BLE001
        log.warning("yt-dlp comments fetch failed for %s: %s", url, e)
        return []
    raw = info.get("comments") or [] if info else []
    out: list[Comment] = []
    for c in raw:
        if c.get("parent") not in (None, "root"):
            continue  # only top-level
        text = (c.get("text") or "").strip()
        if not text:
            continue
        out.append(
            Comment(
                text=text[:1500],
                likes=int(c.get("like_count") or 0),
                replies=int(c.get("reply_count") or 0),
                author=c.get("author"),
            )
        )
        if len(out) >= TOP_N:
            break
    out.sort(key=lambda c: c.likes, reverse=True)
    return out[:TOP_N]


# ---------- Instagram ------------------------------------------------------


def _fetch_instagram_comments(url: str) -> list[Comment]:
    try:
        client = _apify_client()
        run = client.actor(_IG_COMMENT_ACTOR).call(
            run_input={"directUrls": [url], "resultsLimit": TOP_N},
        )
        if not run:
            return []
        dataset_id = run.get("defaultDatasetId")
        if not dataset_id:
            return []
        items = list(client.dataset(dataset_id).iterate_items())
    except Exception as e:  # noqa: BLE001
        log.warning("Apify IG comments fetch failed for %s: %s", url, e)
        return []

    out: list[Comment] = []
    for c in items:
        text = (c.get("text") or c.get("commentText") or "").strip()
        if not text:
            continue
        likes = int(c.get("likesCount") or c.get("likes_count") or 0)
        replies = int(
            c.get("repliesCount") or c.get("replies_count") or c.get("replyCount") or 0
        )
        author = c.get("ownerUsername") or c.get("owner_username") or c.get("author")
        out.append(Comment(text=text[:1500], likes=likes, replies=replies, author=author))
    out.sort(key=lambda c: c.likes, reverse=True)
    return out[:TOP_N]


# ---------- Public dispatcher ---------------------------------------------


def fetch_top_comments(url: str) -> list[Comment]:
    platform = detect_platform(url)
    if platform == "youtube":
        return _fetch_youtube_comments(url)
    if platform == "instagram":
        return _fetch_instagram_comments(url)
    return []


# ---------- Sentiment classifier ------------------------------------------

_SENTIMENT_PROMPT = """Classify each comment into ONE bucket:
- positive: praise, agreement, gratitude
- negative: complaints, disagreement, hostility
- curious: questions, asking for more
- confused: misunderstandings, "wait what?"
- other: spam, off-topic, emoji-only

Return STRICT JSON, one line: {{"counts":{{"positive":N,"negative":N,"curious":N,"confused":N,"other":N}}}}

Comments (numbered):
{comments}
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def classify_sentiment(comments: list[Comment]) -> CommentSentimentMix:
    """One Gemini call. Best-effort; returns empty mix on any failure."""
    if not comments:
        return CommentSentimentMix()
    if not settings.google_api_key:
        log.warning("GOOGLE_API_KEY not set; skipping sentiment")
        return CommentSentimentMix()

    # Lazy import: langchain-google-genai is heavy. We call via the
    # LangChain wrapper rather than the legacy `google.generativeai` SDK
    # because the latter pins an older google-ai-generativelanguage that
    # conflicts with our pinned langchain-google-genai >= 2.1.
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

    numbered = "\n".join(f"{i + 1}. {c.text[:300]}" for i, c in enumerate(comments))
    prompt = _SENTIMENT_PROMPT.format(comments=numbered)

    try:
        resp = llm.invoke(prompt)
        content = resp.content
        if isinstance(content, list):
            content = "".join(
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in content
            )
        text = (content or "").strip()
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini sentiment call failed: %s", e)
        return CommentSentimentMix()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_RE.search(text)
        if not m:
            log.warning("Gemini sentiment returned no JSON: %s", text[:200])
            return CommentSentimentMix()
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            log.warning("Gemini sentiment JSON parse failed: %s on %r", e, text[:200])
            return CommentSentimentMix()

    try:
        counts = data.get("counts", data)  # tolerate flat shape too
        return CommentSentimentMix(
            positive=int(counts.get("positive", 0)),
            negative=int(counts.get("negative", 0)),
            curious=int(counts.get("curious", 0)),
            confused=int(counts.get("confused", 0)),
            other=int(counts.get("other", 0)),
        )
    except (TypeError, ValueError) as e:
        log.warning("Gemini sentiment shape unexpected: %s on %r", e, text[:200])
        return CommentSentimentMix()


def discussion_depth(comments: list[Comment]) -> float | None:
    """Average reply count across the top comments. None if no comments."""
    if not comments:
        return None
    return sum(c.replies for c in comments) / len(comments)
