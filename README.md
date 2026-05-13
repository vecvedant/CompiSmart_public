# CompiSMART

Paste two short-form video URLs (one YouTube, one Instagram). Get an AI chat that knows what's *in* both videos and tells you *why* one performed better than the other — with citations to the exact line of transcript or comment it's pulling from.

> **Status:** ingest + chat + frontend + Cloud Run deploy all live. Cache layer reduces re-ingest of the same URL from ~90s to ~30s.

---

## The 30-second mental model

```
                ┌──────────────────┐
   USER ───►    │   YouTube URL    │     ───► our backend ───► AI chat
                │  Instagram URL   │
                └──────────────────┘
```

Behind that simple-looking flow, the backend pulls metadata + transcripts + comments from both videos, runs them through a chunker, embeds them, stores them in a vector database, and exposes a streaming chat endpoint that retrieves only the relevant pieces per question. Cards show the metrics; chat answers the questions.

---

## The whole machine in one block diagram

```
                   ┌─────────────────────────────────┐
                   │         BROWSER (React UI)      │
                   │   - Paste 2 URLs                │
                   │   - See side-by-side cards      │
                   │   - Stream chat answers         │
                   └────────────┬────────────────────┘
                                │   HTTPS
                                ▼
              ┌─────────────────────────────────────────┐
              │   ONE DOCKER IMAGE on Cloud Run         │
              │                                         │
              │   FastAPI (port 8080)                   │
              │   ├── /                  React UI       │
              │   ├── /api/health                       │
              │   ├── /api/ingest        (POST, ~30-90s)│
              │   ├── /api/chat          (POST, SSE)    │
              │   ├── /api/sessions/:id                 │
              │   └── /api/proxy-image   (IG thumbs)    │
              │                                         │
              │   BGE-small (local CPU embedder)        │
              └────┬─────────────────────────────────┬──┘
                   │                                 │
                   ▼                                 ▼
        ┌──────────────────┐         ┌──────────────────────────┐
        │  Qdrant Cloud    │         │   External APIs          │
        │  (vector DB)     │         │   ┌──────────┐           │
        │                  │         │   │  Apify   │ scraping  │
        │  Stores:         │         │   ├──────────┤           │
        │  - transcript    │         │   │ Deepgram │ STT       │
        │    chunks        │         │   ├──────────┤           │
        │  - comment       │         │   │  Gemini  │ chat +    │
        │    chunks        │         │   │          │ classify  │
        │  - session meta  │         │   ├──────────┤           │
        │  - VIDEO CACHE   │         │   │ pytrends │ trends    │
        │    (transcript + │         │   └──────────┘           │
        │    enrichment by │         └──────────────────────────┘
        │    video_id)     │
        └──────────────────┘
```

Three rules to remember:
1. **One Docker image, one Cloud Run service, one URL.** No CORS. No cross-platform hops.
2. **Qdrant is the only database.** Vectors, session state, and the video cache all live there.
3. **External APIs do the heavy work.** Our server just orchestrates HTTP calls + runs a small embedder.

---

## Step 1 — User pastes 2 URLs

The frontend calls `POST /api/ingest` with both URLs.

```
   url_a (YouTube)    ┐
                      ├──►  POST /api/ingest  ──►  starts ingest pipeline
   url_b (Instagram)  ┘
```

Behind the scenes, both videos are processed **in parallel**:

```
                                 _fetch_one_with_cache(url)
                                          │
                                          ▼
                ┌──────────────────────────────────────────────┐
                │  1. Detect platform (YouTube vs Instagram)    │
                │  2. Pull live metadata (always fresh)         │
                │     - YouTube: yt-dlp                         │
                │     - Instagram: Apify reel scraper           │
                │  3. Look up Qdrant CACHE by video_id          │
                └─────────────────┬────────────────────────────┘
                                  │
                  ┌───────────────┴───────────────┐
                  ▼ CACHE HIT                    ▼ CACHE MISS
       ┌────────────────────┐          ┌────────────────────────┐
       │  Use cached:       │          │  Fetch transcript:     │
       │  - transcript      │          │   - YouTube: 3-tier    │
       │  - top comments    │          │     fallback chain     │
       │  - sentiment       │          │   - Instagram: Deepgram│
       │  - keywords        │          │                        │
       │  - trend status    │          │  Run enrichment:       │
       │                    │          │   - Top comments       │
       │  ~30 seconds       │          │   - Gemini sentiment   │
       └────────────────────┘          │   - Gemini keywords    │
                                       │   - pytrends trend     │
                                       │                        │
                                       │  Save to cache.        │
                                       │  ~60-90 seconds        │
                                       └────────────────────────┘
```

The "3-tier YouTube fallback chain" exists because YouTube blocks scraper traffic from cloud IPs:

```
1. youtube-transcript-api (free, instant)
        ↓ blocked from datacenter IP
2. yt-dlp audio URL → Deepgram
        ↓ also blocked
3. Apify YouTube scraper (residential IPs, ~$0.001/video)  ← always works
```

Once both videos are processed, the backend chunks the transcripts and comments, embeds each chunk with BGE-small (local CPU model), and writes them all to Qdrant.

---

## Step 2 — User sees the video cards

The frontend gets back this JSON shape (one per video):

```
{
  "platform":   "youtube" | "instagram",
  "creator":    "@channel_or_user",
  "follower_count": 1200000,
  "views":      850000,
  "likes":      30000,
  "comments":   5700,

  "engagement_rate":  4.2,    // (likes + comments) / views * 100
  "view_velocity":    16628,  // views per day since upload
  "age_days":         365,
  "life_stage":       "mature",   // fresh / early / mature / saturated

  "topic_keywords":      ["..."],
  "topic_trend_status":  "rising" | "steady" | "declining" | "niche" | "unavailable",
  "discussion_depth":    1.4,
  "comment_sentiment_mix": { positive:0, negative:1, curious:1, ... },

  "top_comments": [...]
}
```

The card renders all of this:

```
   ┌────────────────────────────┐
   │  [thumbnail]               │  ← IG thumbnails proxied via /api/proxy-image
   │                            │     to bypass Meta's anti-hotlinking
   │  @creator_name      4.2%   │
   │  1.2M followers   ENGAGEMENT│
   │  ────────────────────────  │
   │   850K   30K    5.7K       │
   │  VIEWS  LIKES COMMENTS     │
   │  ────────────────────────  │
   │  📅 4 days ago  ⏱ 47s      │
   │  🟢 FRESH   📈 Topic Rising│
   │  #investing #money         │
   └────────────────────────────┘
```

---

## Step 3 — User asks a question

The frontend opens an SSE stream against `POST /api/chat`. Here's what happens for one question:

```
                    "Why did A get more engagement?"
                              │
                              ▼
              ┌─────────────────────────────────┐
              │  1. Embed the question (BGE)    │
              │  2. Search Qdrant TWICE per video│
              │     - 3 transcript chunks       │
              │     - 2 comment chunks          │
              │     = 10 chunks total           │
              │  3. Format as citation-tagged   │
              │     context string              │
              │  4. Build prompt:               │
              │     - System (with metadata)    │
              │     - Chat history              │
              │     - Question + chunks         │
              │  5. Stream Gemini response      │
              └────────────────┬────────────────┘
                               │
                               ▼
              ┌─────────────────────────────────┐
              │   Server-Sent Events stream     │
              │   data: {"token": "Video A's"}  │
              │   data: {"token": " hook plays"}│
              │   data: {"token": " on..."}     │
              │   data: {"token": " [A:0]"}     │← citation
              │   ...                           │
              │   event: done                   │
              └────────────────┬────────────────┘
                               │
                               ▼
                     React renders tokens live,
                     parses [A:N] / [B-comment:N]
                     into colored chips, keeps
                     conversation memory across turns
```

The system prompt enforces a "creator-coach" voice: short paragraphs, no markdown formatting, citations embedded naturally in prose. Memory is kept per session via `RunnableWithMessageHistory`.

---

## What lives where

```
backend/
├── app/
│   ├── main.py              ← FastAPI app, mounts /api/* routes + React UI at /
│   ├── config.py            ← reads .env (Apify, Deepgram, Gemini, Qdrant keys)
│   ├── models.py            ← Pydantic shapes (VideoMeta, Chunk, ChatRequest, ...)
│   ├── sessions.py          ← in-memory session store, falls through to Qdrant
│   │
│   ├── routes/
│   │   ├── ingest.py        ← POST /api/ingest (the cache-aware pipeline)
│   │   ├── chat.py          ← POST /api/chat (SSE streaming)
│   │   ├── sessions.py      ← GET /api/sessions/:id
│   │   └── proxy.py         ← GET /api/proxy-image (IG anti-hotlink bypass)
│   │
│   ├── ingest/
│   │   ├── detect.py        ← URL → platform classifier
│   │   ├── youtube.py       ← yt-dlp + youtube-transcript-api + Apify fallback
│   │   ├── instagram.py     ← Apify reel scrape + Deepgram
│   │   ├── apify_client.py  ← thin SDK wrapper for IG + YT actors
│   │   ├── deepgram_client.py← URL transcription via Deepgram Nova-3
│   │   ├── comments.py      ← top comments + Gemini sentiment classification
│   │   ├── trends.py        ← Gemini keyword extraction + pytrends
│   │   ├── chunking.py      ← sentence-aware ~400-token chunker
│   │   ├── metrics.py       ← engagement_rate + life_stage helpers
│   │   └── errors.py        ← shared IngestError
│   │
│   └── rag/
│       ├── embeddings.py    ← BGE-small wrapper (local CPU)
│       ├── vector_store.py  ← Qdrant client + cache + session metadata
│       ├── prompts.py       ← system prompt + chunk/metadata formatters
│       ├── memory.py        ← session_id → ChatMessageHistory
│       └── chain.py         ← LangChain LCEL pipeline
│
└── scripts/                 ← standalone smoke tests for each phase

frontend/                    ← Vite + React + Tailwind, builds into backend/static
├── src/
│   ├── App.tsx              ← state machine: home → loading → comparison
│   ├── components/
│   │   ├── URLInputForm.tsx
│   │   ├── ProgressUI.tsx   ← 7-step paced loader
│   │   ├── VideoCard.tsx
│   │   ├── ChatPanel.tsx    ← streaming chat with citation chips
│   │   └── ...
│   └── lib/
│       ├── api.ts           ← /api/ingest + SSE chat parser
│       └── parseCitations.ts← splits AI text into text + citation segments
└── public/favicon.svg

cloudbuild.yaml              ← cached Cloud Build pipeline (2-3 min builds)
Dockerfile                   ← 2-stage: Node builds frontend → Python serves it
docs/deploy.md               ← one-time GCP setup walkthrough
```

---

## The cache, explained

Same URL re-ingested = no Apify, no Deepgram, no Gemini calls.

```
   First time:                            Second time:
   ─────────                              ───────────
   - yt-dlp metadata    ~5s               - yt-dlp metadata    ~5s
   - Deepgram          ~10s               - Qdrant cache hit   <1s
   - Apify comments    ~25s               - chunk + embed     ~2s
   - Gemini sentiment   ~5s               - upsert            ~3s
   - Gemini keywords    ~5s               ─────────────────────────
   - pytrends           ~5s               TOTAL               ~30s
   - chunk + embed      ~2s
   - upsert             ~3s
   ─────────────────────────              (nothing in the cache TTL is
   TOTAL              ~60-90s              older than 7 days, so this
                                           keeps working as long as you
                                           re-paste a recent URL)
```

What's cached: transcript, top comments, sentiment, keywords, trend status.
What's NOT cached: views, likes, follower count, engagement rate, life stage. Those are always fresh because they change minute-to-minute.

---

## Tech stack (the short list)

**Frontend:** Vite, React 18, TypeScript, Tailwind CSS, lucide-react.

**Backend:** Python 3.11, FastAPI, uvicorn, Pydantic v2, LangChain LCEL.

**Ingestion:** yt-dlp, youtube-transcript-api, Apify (instagram-scraper, instagram-comment-scraper, instagram-profile-scraper, pintostudio/youtube-transcript-scraper), Deepgram Nova-3, pytrends.

**RAG:** BGE-small-en-v1.5 (local CPU), Qdrant Cloud, Gemini 2.5 Flash (chat), Gemini 2.5 Flash Lite (sentiment + keyword classifier).

**Deploy:** Docker (2-stage), Google Cloud Run (asia-south1, 2 GiB / 1 vCPU), Cloud Build (cloudbuild.yaml with --cache-from).

---

## Cost (real numbers, demo scale)

| Service | Free tier | Demo usage | Cost |
|---|---|---|---|
| Cloud Run | 360k vCPU-sec, 180k GiB-sec/mo | ~2 hours/mo | $0 |
| Qdrant Cloud | 1 GB forever | ~10 MB | $0 |
| BGE embeddings | local CPU | always | $0 |
| Gemini 2.5 Flash | 1500 req/day | ~50/day | $0 |
| Gemini 2.5 Flash Lite | 1000 req/day | ~30/day | $0 |
| Deepgram | $200 credit | ~30 min audio | $0 |
| Apify | $5/mo credit | ~$0.50/mo (cache helps) | $0 |
| **Total** | — | — | **$0/mo** |

At 1,000 creators/day: ~$30/day, dominated by Apify + Deepgram.
At 10,000 creators/day: ~$300/day, with documented migration paths to halve it.

---

## Run it locally

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate                  # Windows
pip install --prefer-binary torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# Configure secrets in ../.env (see ../.env.example)
# Need: APIFY_TOKEN, DEEPGRAM_API_KEY, GOOGLE_API_KEY, QDRANT_URL, QDRANT_API_KEY

# Frontend (one-time build, in another terminal)
cd ../frontend
npm install
npm run build           # outputs to ../backend/static/

# Start the server
cd ../backend
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000.

---

## Deploy

CI/CD via Cloud Run "Continuous Deployment" trigger watching `main`. Push to `main` → Cloud Build builds (~12 min first time, ~2-3 min with `cloudbuild.yaml` cache) → new revision rolls out automatically.

One-time GCP setup is in [`docs/deploy.md`](docs/deploy.md).

---

## License

MIT — see [LICENSE](LICENSE).
