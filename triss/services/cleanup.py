"""
triss.services.cleanup
=======================
Two related responsibilities that both revolve around "temporary state
that must never leak or go stale":

1. SessionManager — tracks the OWNER's current multi-step interaction
   (genlink waiting, batch active, custom batch active, broadcast
   waiting, force-sub add flows, store channel setup, welcome setup,
   auto-delete setup, backup/restore confirmation). Sessions live in
   memory (a single bot process owns exactly one active owner session
   at a time — there is only one OWNER_ID by spec) and expire on their
   own after a timeout so a stale flow can never hijack a later command.

2. periodic_cleanup_loop — a background asyncio task that sweeps expired
   sessions on an interval, so timed-out state never lingers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from triss.config import config

logger = logging.getLogger("triss.cleanup")


@dataclass
class Session:
    kind: str
    data: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)


class SessionManager:
    """Single-owner session state. Not thread-safe across processes by
    design — this bot is meant to run as one process (see README), which
    is what makes in-memory session state safe here instead of requiring
    a distributed lock."""

    def __init__(self, timeout_seconds: int) -> None:
        self._timeout = timeout_seconds
        self._sessions: dict[int, Session] = {}

    def set(self, user_id: int, kind: str, data: Optional[dict] = None) -> None:
        self._sessions[user_id] = Session(kind=kind, data=data or {})

    def get(self, user_id: int) -> Optional[Session]:
        session = self._sessions.get(user_id)
        if session is None:
            return None
        if time.time() - session.updated_at > self._timeout:
            logger.info("Session for user %s (%s) expired; clearing.", user_id, session.kind)
            del self._sessions[user_id]
            return None
        return session

    def touch(self, user_id: int) -> None:
        session = self._sessions.get(user_id)
        if session is not None:
            session.updated_at = time.time()

    def update_data(self, user_id: int, **kwargs) -> None:
        session = self._sessions.get(user_id)
        if session is not None:
            session.data.update(kwargs)
            session.updated_at = time.time()

    def is_in(self, user_id: int, kind: str) -> bool:
        session = self.get(user_id)
        return session is not None and session.kind == kind

    def clear(self, user_id: int) -> None:
        self._sessions.pop(user_id, None)

    def sweep_expired(self) -> int:
        now = time.time()
        expired = [uid for uid, s in self._sessions.items() if now - s.updated_at > self._timeout]
        for uid in expired:
            logger.info("Sweeping expired session for user %s.", uid)
            del self._sessions[uid]
        return len(expired)


session_manager = SessionManager(timeout_seconds=config.session_state_timeout_seconds)


def session_is(kind: str):
    """Builds a Pyrogram filter that matches only when the message sender
    currently has an active, non-expired session of the given kind."""
    from pyrogram import filters as _filters

    async def _func(_, __, message):
        user = message.from_user
        if user is None:
            return False
        session = session_manager.get(user.id)
        return session is not None and session.kind == kind

    return _filters.create(_func)


async def periodic_cleanup_loop(interval_seconds: int = 120) -> None:
    """Runs for the lifetime of the process; cancelled cleanly on shutdown."""
    logger.info("Starting periodic cleanup loop (interval=%ss).", interval_seconds)
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                removed = session_manager.sweep_expired()
                if removed:
                    logger.info("Cleanup swept %d expired session(s).", removed)
            except Exception:
                logger.exception("Error during periodic cleanup sweep (continuing).")
    except asyncio.CancelledError:
        logger.info("Periodic cleanup loop cancelled; shutting down cleanly.")
        raise
