"""URL canonicalization + cross-session asset cache lookup.

Every asset we ingest computes a `canonical_url` — a normalized key for the
URL — and stores it on the row. When a new asset is created, we look up
this key across ALL sessions. If a ready asset already exists for the same
URL, we clone its expensive bits (body_text, metadata, Qdrant chunks)
instead of re-running extraction and embedding.

Why we don't just re-use the same row across sessions: an asset is scoped
to one session in the UI (the user's saved list), so each user gets their
own row. Only the underlying content + vectors are shared.

Canonicalization rules:
  - youtube.com / youtu.be → `youtube:<video_id>`
  - everything else → `<host>/<path>?<sorted-non-tracker-query>`
  - tracker params dropped: utm_*, fbclid, gclid, mc_cid, mc_eid, ref, ref_src
  - fragment (#…) always dropped
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse

from app.db import fetch_one, row_to_dict

log = logging.getLogger(__name__)

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src",
    "feature", "si", "pp",
}

# How long a cached asset stays fresh before we re-ingest.
CACHE_MAX_AGE_DAYS = 14

_YT_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,15}$")


def canonical_url(url: str) -> str:
    """Normalize a URL into a cache lookup key.

    Falls back to the raw URL on any parse error — better to miss the cache
    than to crash an ingest.
    """
    if not url:
        return ""
    try:
        u = urlparse(url.strip())
        host = u.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host.startswith("m."):
            host = host[2:]

        # YouTube special-case — collapse all URL forms to youtube:<videoId>.
        if host in ("youtube.com", "youtu.be"):
            params = dict(parse_qsl(u.query, keep_blank_values=False))
            video_id = params.get("v")
            if not video_id and host == "youtu.be":
                video_id = u.path.lstrip("/").split("/")[0]
            if not video_id and "/shorts/" in u.path:
                video_id = u.path.split("/shorts/", 1)[1].split("/")[0]
            if video_id and _YT_VIDEO_ID.match(video_id):
                return f"youtube:{video_id}"

        # Default: host + clean path + sorted non-tracker query string.
        path = u.path.rstrip("/")
        params = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=False)
                  if k.lower() not in TRACKING_PARAMS]
        params.sort(key=lambda kv: kv[0])
        q = urlencode(params, doseq=False)
        return f"{host}{path}" + (f"?{q}" if q else "")
    except Exception as e:
        log.debug("canonical_url failed for %r: %s", url, e)
        return url


async def find_cached(canonical: str) -> Optional[dict]:
    """Look up the most recent ready asset for a canonical URL across all
    sessions. Returns the asset row dict or None.

    Skips assets where body_text is null/empty (incomplete ingest) or older
    than CACHE_MAX_AGE_DAYS.
    """
    if not canonical:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(days=CACHE_MAX_AGE_DAYS)
    row = await fetch_one(
        """
        select id, type, title, summary, body_text, metadata_json,
               niche_slug, ingest_status, added_at
        from assets
        where canonical_url = $1
          and ingest_status = 'ready'
          and body_text is not null
          and length(body_text) > 50
          and added_at > $2
        order by added_at desc
        limit 1
        """,
        canonical, cutoff,
    )
    if not row:
        return None
    d = row_to_dict(row) or {}
    if d.get("id") is not None:
        d["id"] = str(d["id"])
    # metadata_json comes back as jsonb -> already a dict
    import json
    if isinstance(d.get("metadata_json"), str):
        try:
            d["metadata_json"] = json.loads(d["metadata_json"])
        except json.JSONDecodeError:
            d["metadata_json"] = {}
    return d
