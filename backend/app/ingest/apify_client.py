"""Apify wrapper.

Used for:
  apify/instagram-scraper            -> IG reel metadata + media URL
  apify/instagram-profile-scraper    -> IG follower count for the owner
  pintostudio/youtube-transcript-scraper -> YouTube captions when our IP is
                                            blocked from datacenter ranges
                                            (see ingest/youtube.py)

Apify charges per actor run (~$0.001 per video). Profile scraper is only
called when the reel scraper didn't already return follower count.
The YouTube transcript scraper is only called when both the free captions
API AND yt-dlp's audio URL extraction fail (i.e., on Cloud Run).
"""

from __future__ import annotations

import logging
from typing import Any

from apify_client import ApifyClient

from app.config import settings

log = logging.getLogger(__name__)

REEL_ACTOR = "apify/instagram-scraper"
PROFILE_ACTOR = "apify/instagram-profile-scraper"
YT_TRANSCRIPT_ACTOR = "pintostudio/youtube-transcript-scraper"


def _client() -> ApifyClient:
    if not settings.apify_token:
        raise RuntimeError("APIFY_TOKEN is not set in .env")
    return ApifyClient(settings.apify_token)


def _run_actor(actor_id: str, run_input: dict[str, Any]) -> list[dict[str, Any]]:
    """Run an actor and return its dataset items. Blocks until the run finishes."""
    client = _client()
    log.info("Apify run: actor=%s input=%s", actor_id, run_input)
    run = client.actor(actor_id).call(run_input=run_input)
    if run is None:
        raise RuntimeError(f"Apify actor {actor_id} returned no run")
    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        raise RuntimeError(f"Apify run {run.get('id')} has no dataset")
    items = list(client.dataset(dataset_id).iterate_items())
    log.info("Apify dataset %s returned %d items", dataset_id, len(items))
    return items


def scrape_reel(reel_url: str) -> dict[str, Any]:
    """Scrape a single Instagram reel. Returns the first result item."""
    items = _run_actor(
        REEL_ACTOR,
        {
            "directUrls": [reel_url],
            "resultsType": "details",
            "resultsLimit": 1,
            "addParentData": False,
        },
    )
    if not items:
        raise RuntimeError(f"No Apify items for reel {reel_url}")
    return items[0]


def scrape_profile(username: str) -> dict[str, Any]:
    """Scrape an Instagram profile. Returns the first result item."""
    items = _run_actor(
        PROFILE_ACTOR,
        {"usernames": [username], "resultsLimit": 1},
    )
    if not items:
        raise RuntimeError(f"No Apify items for profile {username}")
    return items[0]


def scrape_youtube_transcript(youtube_url: str) -> dict[str, Any]:
    """Scrape a YouTube video transcript. Returns the first result item.

    Used as the LAST resort in youtube.py's transcript fallback chain --
    only when youtube-transcript-api is blocked AND yt-dlp can't extract
    a media URL (both happen routinely on Cloud Run datacenter IPs).

    Output schema is actor-specific; the caller (`youtube.py`) reads
    multiple possible field names defensively.
    """
    # pintostudio/youtube-transcript-scraper expects `videoUrl` (singular
    # string), not the more common `videoUrls` array shape.
    items = _run_actor(
        YT_TRANSCRIPT_ACTOR,
        {"videoUrl": youtube_url},
    )
    if not items:
        raise RuntimeError(f"No Apify YouTube transcript items for {youtube_url}")
    return items[0]
