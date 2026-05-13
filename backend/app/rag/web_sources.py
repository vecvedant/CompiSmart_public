"""Per-session store of web sources Gemini cited via Search grounding.

We keep this in-memory only. News-style URLs are hot for hours, not days,
so persisting them across container restarts adds no demo value. If the
container restarts, the user just asks the next question and the panel
re-fills.

Dedup is by URL: same URL cited across multiple turns appears once.
"""

from __future__ import annotations

import logging
import threading
from typing import Iterable

from app.models import WebSource

log = logging.getLogger(__name__)

# session_id -> list[WebSource], oldest first.
_store: dict[str, list[WebSource]] = {}
_lock = threading.Lock()


def record_web_sources(session_id: str, sources: Iterable[WebSource]) -> None:
    """Append new sources to the session's list, deduped by URL."""
    new_list = list(sources)
    if not new_list:
        return
    with _lock:
        existing = _store.setdefault(session_id, [])
        seen = {s.url for s in existing}
        added = 0
        for s in new_list:
            if s.url and s.url not in seen:
                existing.append(s)
                seen.add(s.url)
                added += 1
    if added:
        log.info("web_sources: session=%s +%d (total %d)", session_id, added, len(_store[session_id]))


def get_web_sources(session_id: str) -> list[WebSource]:
    """Return all web sources cited so far this session."""
    with _lock:
        return list(_store.get(session_id, []))


def clear_web_sources(session_id: str) -> None:
    """Drop the session's sources (e.g. on session expiry)."""
    with _lock:
        _store.pop(session_id, None)
