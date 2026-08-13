"""
triss.services.logging_service
===============================
Sends compact, non-sensitive event notices to LOG_CHANNEL_ID if it is
configured. Never includes secrets. Silently disabled (with a one-time
debug note) if no log channel is configured.
"""

from __future__ import annotations

import logging
import time

from pyrogram import Client
from pyrogram.errors import RPCError

from triss.config import config

logger = logging.getLogger("triss.logging_service")


async def log_event(client: Client, text: str) -> None:
    if not config.log_channel_id:
        return
    try:
        await client.send_message(config.log_channel_id, text, disable_web_page_preview=True)
    except RPCError:
        logger.warning("Failed to deliver log event to LOG_CHANNEL_ID.", exc_info=True)
    except Exception:
        logger.warning("Unexpected error sending log event.", exc_info=True)


async def log_user_start(client: Client, user_id: int, username: str | None, first_name: str | None) -> None:
    when = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    lines = [
        "🚀 New /start",
        f"User ID: `{user_id}`",
    ]
    if first_name:
        lines.append(f"First name: {first_name}")
    if username:
        lines.append(f"Username: @{username}")
    lines.append(f"Time: {when}")
    await log_event(client, "\n".join(lines))


async def log_security_event(client: Client, text: str) -> None:
    await log_event(client, f"🔐 Security event\n{text}")
