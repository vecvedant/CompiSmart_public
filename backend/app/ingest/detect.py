"""URL → platform detector. Pure function, no I/O."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse, parse_qs

from app.models import Platform

_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_IG_HOSTS = {"instagram.com", "www.instagram.com"}
_YT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")
_IG_PATH_RE = re.compile(r"^/(reel|reels|p)/([a-zA-Z0-9_-]+)/?")


def detect_platform(url: str) -> Platform:
    host = (urlparse(url).hostname or "").lower()
    if host in _YT_HOSTS:
        return "youtube"
    if host in _IG_HOSTS:
        return "instagram"
    raise ValueError(f"Unsupported URL host: {host!r}")


def extract_youtube_id(url: str) -> str:
    """Pull the 11-char video id from any common YouTube URL form."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        vid = parsed.path.lstrip("/").split("/")[0]
        if _YT_ID_RE.match(vid):
            return vid
    if host in _YT_HOSTS:
        # /watch?v=ID
        if parsed.path == "/watch":
            v = parse_qs(parsed.query).get("v", [None])[0]
            if v and _YT_ID_RE.match(v):
                return v
        # /shorts/ID  /embed/ID  /v/ID
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "v"}:
            if _YT_ID_RE.match(parts[1]):
                return parts[1]
    raise ValueError(f"Could not extract YouTube id from {url!r}")


def extract_instagram_shortcode(url: str) -> Optional[str]:
    """Pull the IG shortcode from /reel/<code>/ or /p/<code>/ URLs."""
    parsed = urlparse(url)
    m = _IG_PATH_RE.match(parsed.path)
    return m.group(2) if m else None
