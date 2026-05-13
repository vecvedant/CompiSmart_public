-- CompiSMRT v2 schema.
-- Run this once in the Supabase SQL editor against a fresh project.
-- Session-scoped, no auth: session_id is a UUID generated client-side and
-- stored in localStorage. All rows are owned by that session string.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- niches: static taxonomy (we still keep it as a table so the frontend can
-- discover the list dynamically and so feed_cache can FK to it).
-- ---------------------------------------------------------------------------
create table if not exists niches (
    slug             text primary key,
    label            text not null,
    description      text not null default '',
    search_keywords  text[] not null default '{}',
    rss_feeds        text[] not null default '{}',
    yt_category_id   text,                              -- nullable: not every niche maps
    newsapi_category text,                              -- nullable: 'business' | 'technology' | etc.
    icon             text not null default '',          -- emoji or lucide name
    created_at       timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- feed_cache: one row per niche, refreshed every ~6h.
-- items_json is the aggregator output (mixed news + YT, capped ~40 items).
-- ---------------------------------------------------------------------------
create table if not exists feed_cache (
    niche_slug   text primary key references niches(slug) on delete cascade,
    fetched_at   timestamptz not null default now(),
    items_json   jsonb not null default '[]'::jsonb
);

-- ---------------------------------------------------------------------------
-- assets: user-saved items per session.
-- type ∈ {article, video, note, compare}.
-- compare is a synthetic asset linking two video assets together.
-- ---------------------------------------------------------------------------
create table if not exists assets (
    id            uuid primary key default gen_random_uuid(),
    session_id    text not null,
    type          text not null check (type in ('article', 'video', 'note', 'compare')),
    source_url    text,
    title         text not null,
    summary       text not null default '',
    body_text     text,                                 -- article body or stitched transcript
    metadata_json jsonb not null default '{}'::jsonb,   -- platform-specific fields
    niche_slug    text references niches(slug),
    added_at      timestamptz not null default now(),
    ingest_status text not null default 'pending'      -- pending | ready | failed
        check (ingest_status in ('pending', 'ready', 'failed'))
);

create index if not exists assets_session_idx on assets(session_id, added_at desc);
create index if not exists assets_type_idx on assets(session_id, type);

-- v2.2 — global URL cache. canonical_url is a normalized key (YT video_id,
-- stripped trackers, sorted query params) so two sessions adding the same
-- URL hit the same cache entry. ALTER … IF NOT EXISTS is idempotent so the
-- schema bootstrap re-running on an existing DB is safe.
alter table assets add column if not exists canonical_url text;
create index if not exists assets_canonical_url_idx
    on assets(canonical_url, ingest_status, added_at desc);

-- ---------------------------------------------------------------------------
-- chat_messages: per-session chat history (replaces InMemoryChatMessageHistory).
-- Persists across cold starts and instance switches.
-- ---------------------------------------------------------------------------
create table if not exists chat_messages (
    id          uuid primary key default gen_random_uuid(),
    session_id  text not null,
    turn_idx    int  not null,                          -- monotonic per session
    role        text not null check (role in ('user', 'assistant', 'system')),
    content     text not null,
    metadata    jsonb not null default '{}'::jsonb,    -- e.g. cited asset_ids, web sources
    created_at  timestamptz not null default now(),
    unique (session_id, turn_idx)
);

create index if not exists chat_messages_session_idx
    on chat_messages(session_id, turn_idx);

-- ---------------------------------------------------------------------------
-- drafts: generated/edited content from Build mode.
-- ---------------------------------------------------------------------------
create table if not exists drafts (
    id             uuid primary key default gen_random_uuid(),
    session_id     text not null,
    asset_ids      uuid[] not null default '{}',
    output_type    text not null check (output_type in
        ('blog_post', 'video_script', 'x_thread', 'linkedin_post', 'newsletter')),
    tone           text not null default 'confident',
    length         text not null default 'medium',
    title          text not null default '',
    content_md     text not null default '',
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

create index if not exists drafts_session_idx on drafts(session_id, created_at desc);

-- ---------------------------------------------------------------------------
-- artifacts: claude-code-style outputs spawned by chat intent.
-- kind ∈ {compare, draft, summary, metrics, quotes, ...}
-- payload_json structure depends on kind (see app/artifacts/*.py for shapes).
-- status: pending while streaming, ready when complete, failed on error.
-- ---------------------------------------------------------------------------
create table if not exists artifacts (
    id           uuid primary key default gen_random_uuid(),
    session_id   text not null,
    kind         text not null,
    title        text not null default '',
    status       text not null default 'pending' check (status in ('pending','ready','failed')),
    asset_ids    uuid[] not null default '{}',
    prompt       text not null default '',                  -- the user message that spawned it
    payload_json jsonb not null default '{}'::jsonb,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

create index if not exists artifacts_session_idx on artifacts(session_id, created_at desc);
create index if not exists artifacts_kind_idx    on artifacts(session_id, kind);

-- ---------------------------------------------------------------------------
-- Seed niches.
-- yt_category_id: standard YouTube categoryId where applicable.
-- newsapi_category: NewsAPI top-headlines category enum.
-- ---------------------------------------------------------------------------
insert into niches (slug, label, description, search_keywords, rss_feeds, yt_category_id, newsapi_category, icon) values
    ('tech', 'Tech',
     'Software, hardware, AI, startups, and the people building them.',
     array['technology','AI','software','startup','programming','SaaS'],
     array[
        'https://feeds.feedburner.com/TechCrunch',
        'https://www.theverge.com/rss/index.xml',
        'https://www.wired.com/feed/rss',
        'https://arstechnica.com/feed/'
     ],
     '28', 'technology', '💻'),

    ('finance', 'Finance',
     'Markets, investing, personal finance, and the economy.',
     array['finance','investing','stock market','economy','crypto','personal finance'],
     array[
        'https://www.ft.com/rss/home',
        'https://feeds.bloomberg.com/markets/news.rss',
        'https://www.cnbc.com/id/100003114/device/rss/rss.html'
     ],
     null, 'business', '💰'),

    ('politics', 'Politics',
     'Policy, elections, geopolitics, and current affairs.',
     array['politics','policy','election','geopolitics','government'],
     array[
        'http://feeds.bbci.co.uk/news/politics/rss.xml',
        'https://feeds.npr.org/1014/rss.xml',
        'https://www.politico.com/rss/politicopicks.xml'
     ],
     '25', 'general', '🏛️'),

    ('health', 'Health',
     'Medicine, nutrition, fitness, longevity, and wellbeing.',
     array['health','medicine','nutrition','fitness','wellness','longevity'],
     array[
        'https://www.npr.org/rss/rss.php?id=1027',
        'https://feeds.feedburner.com/medscape/news'
     ],
     null, 'health', '🩺'),

    ('sports', 'Sports',
     'Football, cricket, basketball, F1, and the rest of the field.',
     array['sports','football','soccer','cricket','basketball','f1','tennis'],
     array[
        'https://www.espn.com/espn/rss/news',
        'http://feeds.bbci.co.uk/sport/rss.xml'
     ],
     '17', 'sports', '⚽'),

    ('entertainment', 'Entertainment',
     'Film, TV, music, and pop culture.',
     array['movies','tv','music','celebrity','streaming','hollywood'],
     array[
        'https://variety.com/feed/',
        'https://www.hollywoodreporter.com/feed/'
     ],
     '24', 'entertainment', '🎬'),

    ('self-improvement', 'Self-Improvement',
     'Productivity, habits, psychology, and getting better at being human.',
     array['productivity','habits','self improvement','psychology','focus','discipline'],
     array[
        'https://feeds.feedburner.com/zenhabits',
        'https://jamesclear.com/feed'
     ],
     '22', 'general', '🧠'),

    ('gaming', 'Gaming',
     'Video games, esports, indie devs, and gaming culture.',
     array['gaming','video games','esports','indie game','playstation','xbox','nintendo'],
     array[
        'https://www.ign.com/rss/articles/feed',
        'https://kotaku.com/rss'
     ],
     '20', 'general', '🎮'),

    ('science', 'Science',
     'Physics, biology, space, climate — the frontier of what we know.',
     array['science','physics','biology','space','climate','research'],
     array[
        'https://www.sciencedaily.com/rss/all.xml',
        'https://www.nature.com/nature.rss'
     ],
     '28', 'science', '🔬'),

    ('education', 'Education',
     'Learning, teaching, edtech, and the future of education.',
     array['education','learning','edtech','school','university','online courses'],
     array[
        'https://www.edsurge.com/articles_rss',
        'https://feeds.feedburner.com/hackeducation'
     ],
     '27', 'general', '📚'),

    ('travel', 'Travel',
     'Destinations, travel hacks, culture, and the open road.',
     array['travel','destinations','tourism','adventure','backpacking'],
     array[
        'https://www.lonelyplanet.com/news/feed',
        'https://www.nomadicmatt.com/feed/'
     ],
     '19', 'general', '✈️'),

    ('food', 'Food',
     'Cooking, restaurants, food science, and culinary culture.',
     array['food','cooking','recipes','restaurants','chef','cuisine'],
     array[
        'https://www.seriouseats.com/feed',
        'https://www.eater.com/rss/index.xml'
     ],
     '26', 'general', '🍳')
on conflict (slug) do update set
    label = excluded.label,
    description = excluded.description,
    search_keywords = excluded.search_keywords,
    rss_feeds = excluded.rss_feeds,
    yt_category_id = excluded.yt_category_id,
    newsapi_category = excluded.newsapi_category,
    icon = excluded.icon;
