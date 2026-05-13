"""session_id -> ChatMessageHistory store for the RAG chat.

v2: persistent, Supabase-backed (asyncpg). Survives Cloud Run cold starts.
Falls back to in-memory when SUPABASE_URL isn't set so the legacy smoke
scripts keep working.

LangChain's `RunnableWithMessageHistory` calls into the history class from
inside the running asyncio loop. Older versions of this class wrapped sync
DB calls with `asyncio.run()`, which created a SECOND event loop and
orphaned the asyncpg connection (-> "another operation is in progress").
The fix is to expose native async methods (`aget_messages`, `aadd_messages`):
when present, LangChain awaits them directly on the live loop, which keeps
asyncpg happy.
"""
from __future__ import annotations

import logging
from threading import Lock

from langchain_core.chat_history import (
    BaseChatMessageHistory,
    InMemoryChatMessageHistory,
)
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app import db
from app.db import chat as chat_db

log = logging.getLogger(__name__)

_lock = Lock()
_in_memory: dict[str, InMemoryChatMessageHistory] = {}


class SupabaseChatMessageHistory(BaseChatMessageHistory):
    """One instance per session_id. Reads/writes chat_messages via asyncpg.

    Implements BOTH the sync interface (messages / add_messages) and the
    async one (aget_messages / aadd_messages). LangChain prefers async when
    available, which is what we want — sync entry points still work for
    debugging.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id

    # ----- async path (preferred by LangChain) -----
    async def aget_messages(self) -> list[BaseMessage]:
        rows = await chat_db.list_for_session(self.session_id)
        return _rows_to_messages(rows)

    async def aadd_messages(self, messages: list[BaseMessage]) -> None:
        if not messages:
            return
        next_idx = await chat_db.next_turn_idx(self.session_id)
        for i, m in enumerate(messages):
            await chat_db.insert(
                self.session_id, next_idx + i, _role_of(m), _content_of(m),
            )

    async def aclear(self) -> None:
        await chat_db.clear(self.session_id)

    # ----- sync facade -----
    # These shouldn't normally be hit since aget_messages/aadd_messages
    # exist, but BaseChatMessageHistory requires `messages` and
    # `add_messages` to be defined.
    @property
    def messages(self) -> list[BaseMessage]:
        # If called from sync code (no running loop), spin one up.
        import asyncio
        try:
            return asyncio.run(self.aget_messages())
        except RuntimeError:
            # Inside a running loop — fall back to in-memory empty list.
            # The async path should be the one actually used.
            log.warning("messages property called inside running loop; returning [] (async path should be used)")
            return []

    def add_messages(self, messages: list[BaseMessage]) -> None:
        import asyncio
        try:
            asyncio.run(self.aadd_messages(messages))
        except RuntimeError:
            log.warning("add_messages called inside running loop; dropping (async path should be used)")

    def clear(self) -> None:
        import asyncio
        try:
            asyncio.run(self.aclear())
        except RuntimeError:
            pass


def _role_of(msg: BaseMessage) -> str:
    if isinstance(msg, HumanMessage):
        return "user"
    if isinstance(msg, AIMessage):
        return "assistant"
    if isinstance(msg, SystemMessage):
        return "system"
    return getattr(msg, "type", "user")


def _content_of(msg: BaseMessage) -> str:
    c = msg.content
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in c)
    return str(c)


def _rows_to_messages(rows: list[dict]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for r in rows:
        role = r.get("role")
        content = r.get("content") or ""
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
        elif role == "system":
            out.append(SystemMessage(content=content))
    return out


def get_session_history(session_id: str) -> BaseChatMessageHistory:
    """RunnableWithMessageHistory factory. Postgres-backed if configured,
    in-memory dict otherwise.
    """
    if db.is_configured():
        return SupabaseChatMessageHistory(session_id)

    with _lock:
        if session_id not in _in_memory:
            _in_memory[session_id] = InMemoryChatMessageHistory()
        return _in_memory[session_id]


def clear_session(session_id: str) -> None:
    with _lock:
        _in_memory.pop(session_id, None)


def clear_all() -> None:
    with _lock:
        _in_memory.clear()
