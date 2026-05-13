# Two-stage build:
#   1. Node stage builds the Vite + React frontend into static HTML/JS/CSS.
#   2. Python stage installs deps and copies the built frontend into
#      /app/static so FastAPI can serve it at the root URL while the API
#      lives under /api/*.
#
# v2: dropped torch + sentence-transformers + the BGE bake step. Embeddings
# now go through Google's text-embedding-001 (see app/rag/embeddings.py),
# saving ~1.5 GB image size and ~10s cold start.

# ---------- Stage 1: build the frontend ----------------------------------
FROM node:20-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
# `npm ci` if the lock file exists, else fall back to install (first build
# from a fresh repo doesn't have a lock yet).
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
# Vite is configured to emit to ../backend/static, but inside this build
# stage we want it inside /build/dist instead -- Vite's outDir resolves
# relative to vite.config.ts. We override at build time.
RUN npx vite build --outDir /build/dist --emptyOutDir

# ---------- Stage 2: backend image with frontend baked in ---------------
FROM python:3.11-slim

# ffmpeg: yt-dlp uses it for audio extraction (IG path).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps before copying app code so the layer caches across
# code-only changes.
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/supabase ./supabase
COPY --from=frontend /build/dist ./static

# Cloud Run injects $PORT (typically 8080). Default for local docker run.
ENV PORT=8080
EXPOSE 8080

# Single uvicorn worker. Concurrency is set at the Cloud Run service level
# (--concurrency flag in cloudbuild.yaml).
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
