"""Deepgram Nova-3 wrapper. Audio URL -> timestamped TranscriptSegments.

We pass the media URL directly to Deepgram so it fetches the audio itself.
This keeps Render's bandwidth/RAM out of the loop -- Render just hands
Deepgram a URL and gets back the transcript.
"""

from __future__ import annotations

import logging
from typing import Any

from deepgram import DeepgramClient, PrerecordedOptions

from app.config import settings
from app.models import TranscriptSegment

log = logging.getLogger(__name__)


def _client() -> DeepgramClient:
    if not settings.deepgram_api_key:
        raise RuntimeError("DEEPGRAM_API_KEY is not set in .env")
    return DeepgramClient(settings.deepgram_api_key)


def transcribe_url(media_url: str) -> list[TranscriptSegment]:
    """Send a media URL to Deepgram, return sentence-level timestamped segments.

    Uses utterance-level groupings rather than per-word timestamps -- they
    give us natural sentence boundaries that play well with the chunker.
    """
    options = PrerecordedOptions(
        model="nova-3",
        smart_format=True,
        punctuate=True,
        utterances=True,
        language="en",
    )
    log.info("Deepgram transcribing url=%s", media_url[:80])
    dg = _client()
    response: Any = dg.listen.rest.v("1").transcribe_url(
        {"url": media_url}, options, timeout=120.0
    )

    # Prefer utterances (sentence-level). Fall back to a single channel
    # transcript if utterances weren't returned.
    utterances = getattr(response.results, "utterances", None) or []
    segments: list[TranscriptSegment] = []
    for utt in utterances:
        text = (utt.transcript or "").strip()
        if not text:
            continue
        segments.append(
            TranscriptSegment(text=text, start_sec=float(utt.start), end_sec=float(utt.end))
        )

    if not segments:
        # No utterances -- synthesize one from the whole channel transcript.
        try:
            alt = response.results.channels[0].alternatives[0]
            text = (alt.transcript or "").strip()
            if text:
                # Best guess on duration: last word's end time, or 0.
                words = getattr(alt, "words", []) or []
                end_sec = float(words[-1].end) if words else 0.0
                segments.append(TranscriptSegment(text=text, start_sec=0.0, end_sec=end_sec))
        except (AttributeError, IndexError):
            pass

    if not segments:
        raise RuntimeError(f"Deepgram returned no transcript for {media_url[:80]}")
    log.info("Deepgram returned %d utterances", len(segments))
    return segments
