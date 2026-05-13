"""Extract clean article body text from a URL.

We try multiple User-Agents because some sites (Bloomberg, FT, nltimes.nl,
WSJ, paywalled or geofenced publishers) return 403 to default UAs but serve
the article to Chrome / Googlebot / Facebookbot. Once we have HTML,
trafilatura extracts the main content.

Returns (body_text, title). Either can be None if every fetch attempt
fails or extraction yields nothing useful.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

log = logging.getLogger(__name__)

ARTICLE_TIMEOUT_S = 10.0

# Try these in order. Most sites accept the first; the rest are fallbacks
# for publishers that block headless / non-browser UAs.
USER_AGENTS = (
    # Recent Chrome on Windows — accepted by most paywalled / bot-checked sites.
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Googlebot — many news sites serve full articles to it for SEO.
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    # Facebook external hit — used by their crawler for OG previews.
    "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
)

# Minimum useful body length. Below this it's probably a "subscribe to read"
# stub, an error page, or a redirect we couldn't parse.
MIN_BODY_CHARS = 200


async def extract_article(url: str) -> tuple[Optional[str], Optional[str]]:
    """Fetch via one of several UAs, then extract body via trafilatura.

    Returns (body, title). Caller decides what to do if both are None.
    """
    html: Optional[str] = None
    last_err: Optional[str] = None

    async with httpx.AsyncClient(timeout=ARTICLE_TIMEOUT_S, follow_redirects=True) as client:
        for ua in USER_AGENTS:
            try:
                r = await client.get(url, headers={
                    "User-Agent": ua,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                })
                r.raise_for_status()
                html = r.text
                if html:
                    log.debug("Article fetch OK with UA=%s for %s", ua[:30], url)
                    break
            except httpx.HTTPStatusError as e:
                last_err = f"{e.response.status_code}"
                log.debug("UA %s -> %s for %s", ua[:30], last_err, url)
                continue
            except Exception as e:
                last_err = type(e).__name__
                log.debug("UA %s -> %s for %s", ua[:30], last_err, url)
                continue

    if not html:
        log.warning("All UAs failed for url=%s (last=%s)", url, last_err)
        return None, None

    body, title = await asyncio.to_thread(_extract_sync, html, url)
    if body and len(body) < MIN_BODY_CHARS:
        log.info("Extracted body too short (%d chars) — discarding for url=%s", len(body), url)
        body = None
    if body:
        log.info("Article extracted url=%s len=%d", url, len(body))
    else:
        log.warning("Trafilatura returned empty body for url=%s", url)
    return body, title


def _extract_sync(html: str, url: str) -> tuple[Optional[str], Optional[str]]:
    import trafilatura

    body = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_recall=True,
        deduplicate=True,
    )

    title: Optional[str] = None
    try:
        meta = trafilatura.extract_metadata(html)
        if meta:
            title = meta.title
    except Exception:
        title = None

    return body, title
