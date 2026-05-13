"""Sentence-aware chunker for video transcripts.

Splits a list of timestamped TranscriptSegments into ~target_tokens chunks
with a small overlap, preferring to break at sentence boundaries. Each output
Chunk carries start_sec / end_sec spanning the segments it absorbed.
"""

from __future__ import annotations

import re
from typing import Iterable

import tiktoken

from app.config import settings
from app.models import Chunk, TranscriptSegment, VideoSlot

_ENCODER = tiktoken.get_encoding("cl100k_base")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def _ntokens(text: str) -> int:
    return len(_ENCODER.encode(text))


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_END.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def chunk_transcript(
    segments: Iterable[TranscriptSegment],
    video_slot: VideoSlot,
    target_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[Chunk]:
    target = target_tokens or settings.chunk_target_tokens
    overlap = overlap_tokens or settings.chunk_overlap_tokens

    seg_list = list(segments)
    if not seg_list:
        return []

    # Flatten into sentence-level units, each tagged with the time window
    # of the segment(s) it came from.
    units: list[tuple[str, float, float]] = []
    for seg in seg_list:
        sentences = _split_sentences(seg.text)
        if not sentences:
            continue
        if len(sentences) == 1:
            units.append((sentences[0], seg.start_sec, seg.end_sec))
        else:
            # Distribute the segment's time window across its sentences.
            span = seg.end_sec - seg.start_sec
            per = span / len(sentences) if sentences else span
            for i, s in enumerate(sentences):
                units.append((s, seg.start_sec + i * per, seg.start_sec + (i + 1) * per))

    if not units:
        return []

    chunks: list[Chunk] = []
    cur_text: list[str] = []
    cur_tokens = 0
    cur_start: float | None = None
    cur_end: float | None = None
    idx = 0
    i = 0

    while i < len(units):
        sent, s_start, s_end = units[i]
        sent_tokens = _ntokens(sent)

        if cur_start is None:
            cur_start = s_start
        cur_text.append(sent)
        cur_tokens += sent_tokens
        cur_end = s_end
        i += 1

        if cur_tokens >= target:
            chunks.append(
                Chunk(
                    video_slot=video_slot,
                    chunk_idx=idx,
                    kind="transcript",
                    text=" ".join(cur_text),
                    start_sec=cur_start,
                    end_sec=cur_end,
                )
            )
            idx += 1
            # Build overlap: pull sentences from the tail until we have ~overlap tokens.
            tail: list[str] = []
            tail_tokens = 0
            for s in reversed(cur_text):
                t = _ntokens(s)
                if tail_tokens + t > overlap:
                    break
                tail.insert(0, s)
                tail_tokens += t
            cur_text = tail
            cur_tokens = tail_tokens
            cur_start = None if not tail else cur_end  # rough; overlap re-uses end
            # Note: cur_end stays; first new sentence will overwrite.

    if cur_text and cur_start is not None and cur_end is not None:
        chunks.append(
            Chunk(
                video_slot=video_slot,
                chunk_idx=idx,
                kind="transcript",
                text=" ".join(cur_text),
                start_sec=cur_start,
                end_sec=cur_end,
            )
        )

    return chunks
