"""FastAPI entry point.

Single port serves both the API (/api/*) and the static React frontend (/).
The frontend build output (Vite's dist/) is copied to backend/static/ during
the Docker build. In dev, run `npm run build -- --watch` from frontend/ in
another terminal so FastAPI picks up new builds.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.db import is_configured as db_is_configured
from app.db.schema import bootstrap_schema
from app.routes.artifacts import router as artifacts_router
from app.routes.assets import router as assets_router
from app.routes.build import router as build_router
from app.routes.chat import router as chat_router
from app.routes.compare import router as compare_router
from app.routes.drafts import router as drafts_router
from app.routes.feed import router as feed_router
from app.routes.ingest import router as ingest_router
from app.routes.niches import router as niches_router
from app.routes.proxy import router as proxy_router
from app.routes.sessions import router as sessions_router
from app.routes.sources import router as sources_router
from app.routes.verdict import router as verdict_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s : %(message)s",
)
log = logging.getLogger("rag_returns")


# ---------- App ------------------------------------------------------------

app = FastAPI(title="RAG Returns", version="0.1.0")


# ---------- Startup --------------------------------------------------------
# We used to load a local BGE PyTorch model on startup (200-500 MB RAM,
# ~10s cold) to dodge a race on first request. We now embed via the Gemini
# API (see app/rag/embeddings.py), so there's nothing heavy to warm —
# prewarm() is a no-op kept only for callsite compatibility.

@app.on_event("startup")
async def _bootstrap_db() -> None:
    if not db_is_configured():
        log.warning("SUPABASE_URL not set — v2 routes (feed, assets, chat history, drafts) will return 503. Compare-only mode still works.")
        return
    try:
        ran = await bootstrap_schema()
        log.info("DB ready (schema %s)", "applied" if ran else "already present")
    except Exception as e:
        log.exception("DB bootstrap failed: %s", e)


# ---------- Middleware -----------------------------------------------------

class RequestLogMiddleware(BaseHTTPMiddleware):
    """One log line per request: method, path, status, duration_ms."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            log.exception(
                "%s %s -> 500 (unhandled)", request.method, request.url.path
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        log.info(
            "%s %s -> %d in %.0fms",
            request.method,
            request.url.path,
            status,
            duration_ms,
        )
        return response


app.add_middleware(RequestLogMiddleware)

# CORS: open by default so curl / browser dev tools / external testing tools
# can hit the deployed API. Lock down in production via the CORS_ORIGINS env
# var (comma-separated). When the SPA is served from the same origin (the
# default deployment), CORS is irrelevant — but having it permissive doesn't
# hurt for demo URLs and dev probes.
_cors_env = os.getenv("CORS_ORIGINS", "*").strip()
_cors_origins = ["*"] if _cors_env == "*" else [o.strip() for o in _cors_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Routes ---------------------------------------------------------

api = APIRouter(prefix="/api")


@api.get("/health")
async def health() -> dict:
    """Liveness probe. Cloud Run hits this; cron-job.org should too."""
    return {"ok": True}


api.include_router(ingest_router)
api.include_router(chat_router)
api.include_router(sessions_router)
api.include_router(sources_router)
api.include_router(verdict_router)
api.include_router(proxy_router)
# v2 routes — niche-driven content studio.
api.include_router(niches_router)
api.include_router(feed_router)
api.include_router(assets_router)
api.include_router(build_router)
api.include_router(drafts_router)
api.include_router(compare_router)
api.include_router(artifacts_router)
app.include_router(api)


# Serve the built React app at the root. If the build directory doesn't exist
# yet (early dev), don't crash -- just expose the API with a small JSON hint.
_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    # Mount static assets at /assets (Vite emits a /assets subdir with the
    # hashed JS + CSS + img files). We DON'T mount StaticFiles at root
    # anymore because that 404s on React Router routes like /feed/:niche
    # when hit directly (browser refresh, deep link, back button). Instead
    # we serve index.html for any non-API path via the catch-all below.
    _assets_dir = _static_dir / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    _index = _static_dir / "index.html"

    @app.get("/{full_path:path}")
    async def _spa_catch_all(full_path: str) -> FileResponse:
        """SPA fallback: serve index.html for any GET that didn't match an
        /api/* route or /assets/* file. React Router handles the URL
        client-side. This fixes 404s on /feed/:niche, /compare/:a/:b,
        /drafts when hit directly.

        First we check if the path is a real top-level file (favicon.ico,
        robots.txt, etc.) and serve it directly. Otherwise fall through
        to index.html.
        """
        # Block any /api/ leaks — FastAPI's route resolver should match
        # the API routes first, but defensive check in case of routing
        # weirdness.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)

        # Real file at the top of /static? Serve it.
        if full_path:
            candidate = _static_dir / full_path
            if candidate.is_file() and candidate.resolve().is_relative_to(_static_dir.resolve()):
                return FileResponse(candidate)

        # Otherwise SPA route — serve index.html so React Router can route.
        if _index.is_file():
            return FileResponse(_index)
        raise HTTPException(status_code=404, detail="Frontend not built")

    log.info("Mounted SPA from %s (catch-all → index.html)", _static_dir)
else:
    log.warning(
        "No static frontend at %s -- API-only mode. "
        "Build the frontend with `cd frontend && npm run build` to enable the UI.",
        _static_dir,
    )

    @app.get("/")
    async def root_placeholder() -> JSONResponse:
        return JSONResponse(
            {
                "ok": True,
                "message": "API is up. Frontend not built yet.",
                "try": "/api/health, POST /api/ingest",
            }
        )
