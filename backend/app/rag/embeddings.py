"""Embeddings via Google's text-embedding-004 (Gemini API).

We dropped sentence-transformers + torch (~1 GB on disk, ~500 MB RAM, ~10 s
cold-start) because Google's hosted embedding endpoint is:
  - free at our demo scale (1500 RPM, generous daily limits)
  - faster (one HTTPS call, batched)
  - zero local cold-start
  - 768-dim instead of 384 (a small quality bump)

Same module interface (`embed_query`, `embed_texts`, `embed_dim`,
`prewarm`) so nothing downstream changed.

When you switch demo accounts, set:
  GEMINI_API_KEY=...
or:
  GOOGLE_API_KEY=...
Either is read into settings.google_api_key.
"""
from __future__ import annotations

import logging
import threading
from functools import lru_cache
from typing import Iterable, Optional

from google import genai
from google.genai import types as genai_types

from app.config import settings

log = logging.getLogger(__name__)

EMBED_MODEL = "gemini-embedding-001"   # replaces text-embedding-004 (retired)
EMBED_DIM = 768                        # gemini-embedding-001 supports 768/1536/3072

# Google's embed endpoint accepts up to 100 inputs per call. We use 50 so
# token-per-input ceiling (each input can be ~2k tokens before the SDK
# splits) stays well inside the per-request limit.
BATCH_SIZE = 50


_client_lock = threading.Lock()
_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        if not settings.google_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY / GOOGLE_API_KEY not set. Set one in .env."
            )
        _client = genai.Client(api_key=settings.google_api_key)
        log.info("Initialized Gemini embedding client (model=%s)", EMBED_MODEL)
    return _client


def prewarm() -> None:
    """No-op for API embeddings — kept so callers don't need to change."""
    _get_client()


def embed_dim() -> int:
    return EMBED_DIM


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    """Batch-embed a list of strings via Gemini. Returns a list of float vectors.

    Empty or whitespace-only inputs become zero vectors so the indexing of
    inputs <-> outputs stays aligned (callers iterate `zip(chunks, vectors)`).
    """
    arr = [t if t else " " for t in texts]
    if not arr:
        return []

    client = _get_client()
    out: list[list[float]] = []
    for i in range(0, len(arr), BATCH_SIZE):
        batch = arr[i : i + BATCH_SIZE]
        resp = client.models.embed_content(
            model=EMBED_MODEL,
            contents=batch,
            config=genai_types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=EMBED_DIM,
            ),
        )
        out.extend(e.values for e in resp.embeddings)
    return out


def embed_query(text: str) -> list[float]:
    """Single-string embed using the RETRIEVAL_QUERY task type — Gemini
    optimizes the embedding for matching against RETRIEVAL_DOCUMENT vectors.
    """
    if not text:
        text = " "
    client = _get_client()
    resp = client.models.embed_content(
        model=EMBED_MODEL,
        contents=[text],
        config=genai_types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=EMBED_DIM,
        ),
    )
    return resp.embeddings[0].values
