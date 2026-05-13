"""Niche taxonomy — single source of truth used by feed scrapers.

Mirrors backend/supabase/schema.sql seed. We keep an in-code copy so the
scrapers don't need a round-trip to Supabase just to read static metadata,
and so `GET /api/niches` is instant.

If you change a niche here, update schema.sql too (or re-run the seed
INSERT … ON CONFLICT DO UPDATE block).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Niche:
    slug: str
    label: str
    description: str
    search_keywords: list[str]
    rss_feeds: list[str]
    yt_category_id: Optional[str] = None
    newsapi_category: Optional[str] = None
    icon: str = ""
    # v2.1: per-niche subreddit list (no `r/` prefix). Used by reddit_scraper.
    subreddits: tuple[str, ...] = ()
    # Whether HackerNews should contribute to this niche's feed.
    use_hackernews: bool = False

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "label": self.label,
            "description": self.description,
            "search_keywords": self.search_keywords,
            "rss_feeds": self.rss_feeds,
            "yt_category_id": self.yt_category_id,
            "newsapi_category": self.newsapi_category,
            "icon": self.icon,
            "subreddits": list(self.subreddits),
            "use_hackernews": self.use_hackernews,
        }


NICHES: list[Niche] = [
    Niche(
        slug="tech",
        label="Tech",
        description="Software, hardware, AI, startups, and the people building them.",
        search_keywords=["technology", "AI", "software", "startup", "programming", "SaaS"],
        rss_feeds=[
            "https://feeds.feedburner.com/TechCrunch",
            "https://www.theverge.com/rss/index.xml",
            "https://www.wired.com/feed/rss",
            "https://arstechnica.com/feed/",
        ],
        yt_category_id="28",
        newsapi_category="technology",
        icon="💻",
        subreddits=("technology", "programming", "MachineLearning", "artificial"),
        use_hackernews=True,
    ),
    Niche(
        slug="finance",
        label="Finance",
        description="Markets, investing, personal finance, and the economy.",
        search_keywords=["finance", "investing", "stock market", "economy", "crypto", "personal finance"],
        rss_feeds=[
            "https://www.ft.com/rss/home",
            "https://feeds.bloomberg.com/markets/news.rss",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        ],
        yt_category_id=None,
        newsapi_category="business",
        icon="💰",
        subreddits=("personalfinance", "investing", "stocks", "CryptoCurrency", "wallstreetbets"),
        use_hackernews=True,
    ),
    Niche(
        slug="politics",
        label="Politics",
        description="Policy, elections, geopolitics, and current affairs.",
        search_keywords=["politics", "policy", "election", "geopolitics", "government"],
        rss_feeds=[
            "http://feeds.bbci.co.uk/news/politics/rss.xml",
            "https://feeds.npr.org/1014/rss.xml",
            "https://www.politico.com/rss/politicopicks.xml",
        ],
        yt_category_id="25",
        newsapi_category="general",
        icon="🏛️",
        subreddits=("politics", "geopolitics", "worldnews"),
    ),
    Niche(
        slug="health",
        label="Health",
        description="Medicine, nutrition, fitness, longevity, and wellbeing.",
        search_keywords=["health", "medicine", "nutrition", "fitness", "wellness", "longevity"],
        rss_feeds=[
            "https://www.npr.org/rss/rss.php?id=1027",
            "https://feeds.feedburner.com/medscape/news",
        ],
        yt_category_id=None,
        newsapi_category="health",
        icon="🩺",
        subreddits=("Health", "nutrition", "Fitness", "longevity"),
    ),
    Niche(
        slug="sports",
        label="Sports",
        description="Football, cricket, basketball, F1, and the rest of the field.",
        search_keywords=["sports", "football", "soccer", "cricket", "basketball", "f1", "tennis"],
        rss_feeds=[
            "https://www.espn.com/espn/rss/news",
            "http://feeds.bbci.co.uk/sport/rss.xml",
        ],
        yt_category_id="17",
        newsapi_category="sports",
        icon="⚽",
        subreddits=("sports", "soccer", "nba", "nfl", "formula1", "Cricket"),
    ),
    Niche(
        slug="entertainment",
        label="Entertainment",
        description="Film, TV, music, and pop culture.",
        search_keywords=["movies", "tv", "music", "celebrity", "streaming", "hollywood"],
        rss_feeds=[
            "https://variety.com/feed/",
            "https://www.hollywoodreporter.com/feed/",
        ],
        yt_category_id="24",
        newsapi_category="entertainment",
        icon="🎬",
        subreddits=("movies", "television", "Music", "popculturechat"),
    ),
    Niche(
        slug="self-improvement",
        label="Self-Improvement",
        description="Productivity, habits, psychology, and getting better at being human.",
        search_keywords=["productivity", "habits", "self improvement", "psychology", "focus", "discipline"],
        rss_feeds=[
            "https://feeds.feedburner.com/zenhabits",
            "https://jamesclear.com/feed",
        ],
        yt_category_id="22",
        newsapi_category="general",
        icon="🧠",
        subreddits=("productivity", "selfimprovement", "getdisciplined", "decidingtobebetter"),
    ),
    Niche(
        slug="gaming",
        label="Gaming",
        description="Video games, esports, indie devs, and gaming culture.",
        search_keywords=["gaming", "video games", "esports", "indie game", "playstation", "xbox", "nintendo"],
        rss_feeds=[
            "https://www.ign.com/rss/articles/feed",
            "https://kotaku.com/rss",
        ],
        yt_category_id="20",
        newsapi_category="general",
        icon="🎮",
        subreddits=("gaming", "Games", "pcgaming", "IndieGaming"),
    ),
    Niche(
        slug="science",
        label="Science",
        description="Physics, biology, space, climate — the frontier of what we know.",
        search_keywords=["science", "physics", "biology", "space", "climate", "research"],
        rss_feeds=[
            "https://www.sciencedaily.com/rss/all.xml",
            "https://www.nature.com/nature.rss",
        ],
        yt_category_id="28",
        newsapi_category="science",
        icon="🔬",
        subreddits=("science", "askscience", "space", "Physics", "biology"),
        use_hackernews=True,
    ),
    Niche(
        slug="education",
        label="Education",
        description="Learning, teaching, edtech, and the future of education.",
        search_keywords=["education", "learning", "edtech", "school", "university", "online courses"],
        rss_feeds=[
            "https://www.edsurge.com/articles_rss",
            "https://feeds.feedburner.com/hackeducation",
        ],
        yt_category_id="27",
        newsapi_category="general",
        icon="📚",
        subreddits=("education", "teachers", "GetStudying"),
    ),
    Niche(
        slug="travel",
        label="Travel",
        description="Destinations, travel hacks, culture, and the open road.",
        search_keywords=["travel", "destinations", "tourism", "adventure", "backpacking"],
        rss_feeds=[
            "https://www.lonelyplanet.com/news/feed",
            "https://www.nomadicmatt.com/feed/",
        ],
        yt_category_id="19",
        newsapi_category="general",
        icon="✈️",
        subreddits=("travel", "solotravel", "backpacking", "digitalnomad"),
    ),
    Niche(
        slug="food",
        label="Food",
        description="Cooking, restaurants, food science, and culinary culture.",
        search_keywords=["food", "cooking", "recipes", "restaurants", "chef", "cuisine"],
        rss_feeds=[
            "https://www.seriouseats.com/feed",
            "https://www.eater.com/rss/index.xml",
        ],
        yt_category_id="26",
        newsapi_category="general",
        icon="🍳",
        subreddits=("food", "Cooking", "MealPrepSunday", "AskCulinary"),
    ),
]


_BY_SLUG: dict[str, Niche] = {n.slug: n for n in NICHES}


def get(slug: str) -> Optional[Niche]:
    return _BY_SLUG.get(slug)


def all_slugs() -> list[str]:
    return [n.slug for n in NICHES]
