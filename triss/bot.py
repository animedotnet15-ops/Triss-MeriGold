"""
triss.bot
=========
Owns the single Kurigram `Client` instance. Handler modules are imported
at the bottom of this file (after `app` exists) purely for their
side-effect of registering `@app.on_message` / `@app.on_callback_query`
decorators — this avoids circular imports while keeping each handler
file self-contained.
"""

from __future__ import annotations

import asyncio
import logging

from pyrogram import Client

from triss.config import config
from triss.database.mongodb import database
from triss.services.cleanup import periodic_cleanup_loop

logger = logging.getLogger("triss.bot")

app = Client(
    name=config.session_name,
    api_id=config.api_id,
    api_hash=config.api_hash,
    bot_token=config.bot_token,
    in_memory=True,
)

_cleanup_task: asyncio.Task | None = None


async def startup() -> None:
    logger.info("Starting Triss File Store Bot...")
    await database.connect()
    await app.start()
    me = await app.get_me()
    app.username = me.username  # convenient cache used by deep-link builders
    global _cleanup_task
    _cleanup_task = asyncio.create_task(periodic_cleanup_loop())
    logger.info("Bot started as @%s (id=%s).", me.username, me.id)


async def shutdown() -> None:
    logger.info("Shutting down Triss File Store Bot...")
    if _cleanup_task is not None:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
    try:
        await app.stop()
    except Exception:
        logger.exception("Error while stopping the Telegram client.")
    await database.close()
    logger.info("Shutdown complete.")


# Import handler modules for their registration side effects. Order does
# not matter for filter dispatch (Pyrogram routes by filter, not import
# order) but is kept roughly command-then-callback for readability.
from triss.handlers import start as _start_handlers  # noqa: E402,F401
from triss.handlers import genlink as _genlink_handlers  # noqa: E402,F401
from triss.handlers import batch as _batch_handlers  # noqa: E402,F401
from triss.handlers import custom_batch as _custom_batch_handlers  # noqa: E402,F401
from triss.handlers import broadcast as _broadcast_handlers  # noqa: E402,F401
from triss.handlers import settings as _settings_handlers  # noqa: E402,F401
from triss.handlers import callbacks as _callback_handlers  # noqa: E402,F401
