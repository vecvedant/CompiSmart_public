"""Paragraph-aware text chunker for article bodies.

Simpler than the transcript chunker: no timestamps, just split on blank lines,
then greedy-accumulate paragraphs until we hit ~target_tokens, with a small
sentence-level overlap into the next chunk.
"""
from __future__ import annotations

import re

import tiktoken

from app.config import settings

_ENCODER = tiktoken.get_encoding("cl100k_base")
_PARA_SPLIT = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def _ntokens(text: str) -> int:
    return len(_ENCODER.encode(text))


def chunk_article(body: str, target_tokens: int | None = None, overlap_tokens: int | None = None) -> list[str]:
    target = target_tokens or settings.chunk_target_tokens
    overlap = overlap_tokens or settings.chunk_overlap_tokens

    body = (body or "").strip()
    if not body:
        return []

    paragraphs = [p.strip() for p in _PARA_SPLIT.split(body) if p.strip()]
    chunks: list[str] = []
    cur: list[str] = []
    cur_tokens = 0

    for p in paragraphs:
        p_tokens = _ntokens(p)
        if p_tokens > target * 1.5:
            # Single huge paragraph — flush current and split it sentence-wise.
            if cur:
                chunks.append("\n\n".join(cur))
                cur, cur_tokens = [], 0
            chunks.extend(_split_long(p, target, overlap))
            continue

        if cur_tokens + p_tokens > target and cur:
            chunks.append("\n\n".join(cur))
            tail = _tail_for_overlap(cur, overlap)
            cur = [tail] if tail else []
            cur_tokens = _ntokens(tail) if tail else 0

        cur.append(p)
        cur_tokens += p_tokens

    if cur:
        chunks.append("\n\n".join(cur))

    return chunks


def _split_long(paragraph: str, target: int, overlap: int) -> list[str]:
    sentences = [s.strip() for s in _SENTENCE_END.split(paragraph) if s.strip()]
    chunks: list[str] = []
    cur: list[str] = []
    cur_tokens = 0
    for s in sentences:
        t = _ntokens(s)
        if cur_tokens + t > target and cur:
            chunks.append(" ".join(cur))
            tail = _tail_for_overlap(cur, overlap)
            cur = [tail] if tail else []
            cur_tokens = _ntokens(tail) if tail else 0
        cur.append(s)
        cur_tokens += t
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def _tail_for_overlap(units: list[str], overlap: int) -> str:
    """Take the last few units up to ~overlap tokens."""
    tail: list[str] = []
    tt = 0
    for u in reversed(units):
        t = _ntokens(u)
        if tt + t > overlap and tail:
            break
        tail.insert(0, u)
        tt += t
        if tt >= overlap:
            break
    return " ".join(tail)
