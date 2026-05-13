"""GET /api/proxy-image?url=<encoded> -- proxy CDN images that block direct
browser requests.

Why: Meta's CDN (scontent-*.cdninstagram.com) refuses image requests from
browsers due to anti-hotlinking, even when the URL is otherwise valid.
We fetch server-side with a desktop-browser User-Agent and stream the
bytes back. YouTube's i.ytimg.com works fine in <img>, so this is only
called for IG cards in the UI.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

log = logging.getLogger(__name__)
router = APIRouter()

# Anti-SSRF: only allow hosts we know we'd ask for. Add to this list as new
# CDNs come up. Anything else returns 400.
_ALLOWED_HOST_SUFFIXES = (
    ".cdninstagram.com",
    ".fbcdn.net",
    ".ytimg.com",
    "ytimg.com",
)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _host_allowed(host: str) -> bool:
    host = host.lower()
    return any(host == s.lstrip(".") or host.endswith(s) for s in _ALLOWED_HOST_SUFFIXES)


@router.get("/proxy-image")
async def proxy_image(url: str = Query(..., min_length=10)):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http(s) URLs allowed")
    host = parsed.hostname or ""
    if not _host_allowed(host):
        raise HTTPException(status_code=400, detail=f"Host not allowed: {host}")

    try:
        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(10.0),
            headers=_BROWSER_HEADERS,
        )
        resp = await client.get(url)
    except httpx.HTTPError as e:
        await client.aclose()
        log.warning("proxy-image fetch failed for %s: %s", host, e)
        raise HTTPException(status_code=502, detail=f"upstream fetch failed: {e}") from e

    if resp.status_code >= 400:
        await client.aclose()
        log.info("proxy-image upstream %d for %s", resp.status_code, host)
        raise HTTPException(status_code=resp.status_code, detail="upstream rejected")

    content_type = resp.headers.get("content-type", "image/jpeg")

    async def stream():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        stream(),
        media_type=content_type,
        headers={
            # Cache the proxied image for 1 day in the browser. CDN URLs
            # expire in ~24h anyway, so this is roughly aligned.
            "Cache-Control": "public, max-age=86400",
        },
    )
