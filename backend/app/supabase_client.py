"""DEPRECATED — kept as a thin shim that delegates to the `db.*` package.

The codebase originally used the supabase-py REST SDK. We now talk to
Supabase Postgres directly via asyncpg (see `app/db/__init__.py`), which
is faster and removes the service-role-key requirement.

This module re-exports the same function names callers were using before
so the rest of the code didn't need a sweeping rename. New code should
import from `app.db.*` directly:

    from app.db import assets, feed_cache, chat, drafts
"""
from __future__ import annotations

from app.db import is_configured  # re-export
from app.db import assets as _assets
from app.db import chat as _chat
from app.db import drafts as _drafts
from app.db import feed_cache as _feed_cache


# --- feed cache ---------------------------------------------------------
async def fetch_feed_cache(niche_slug: str):
    return await _feed_cache.get(niche_slug)


async def upsert_feed_cache(niche_slug: str, items: list[dict]) -> None:
    await _feed_cache.upsert(niche_slug, items)


# --- assets -------------------------------------------------------------
async def insert_asset(asset: dict) -> dict:
    return await _assets.insert(asset)


async def update_asset(asset_id: str, patch: dict) -> None:
    await _assets.update(asset_id, patch)


async def list_assets(session_id: str) -> list[dict]:
    return await _assets.list_for_session(session_id)


async def delete_asset(asset_id: str, session_id: str) -> None:
    await _assets.delete(asset_id, session_id)


# --- chat ---------------------------------------------------------------
async def insert_chat_message(session_id: str, turn_idx: int, role: str, content: str, metadata: dict | None = None) -> None:
    await _chat.insert(session_id, turn_idx, role, content, metadata)


async def list_chat_messages(session_id: str) -> list[dict]:
    return await _chat.list_for_session(session_id)


async def next_turn_idx(session_id: str) -> int:
    return await _chat.next_turn_idx(session_id)


# --- drafts -------------------------------------------------------------
async def upsert_draft(draft: dict) -> dict:
    return await _drafts.upsert(draft)


async def list_drafts(session_id: str) -> list[dict]:
    return await _drafts.list_for_session(session_id)
