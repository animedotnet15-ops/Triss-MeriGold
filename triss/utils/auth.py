"""
triss.utils.auth
=================
Single source of truth for "is this the owner?". Never authorize based
on username, first/last name, or unvalidated callback data — always the
numeric OWNER_ID compared against the actual Telegram user_id Pyrogram
attaches to the update.
"""

from __future__ import annotations

from pyrogram import filters
from pyrogram.types import Message, CallbackQuery

from triss.config import config


def is_owner(user_id: int | None) -> bool:
    return user_id is not None and user_id == config.owner_id


owner_filter = filters.user(config.owner_id)


async def deny_if_not_owner(update: Message | CallbackQuery) -> bool:
    """Returns True (and answers/replies) if the update should be denied."""
    user = update.from_user
    if user is None or not is_owner(user.id):
        if isinstance(update, CallbackQuery):
            await update.answer("🚫 Owner only.", show_alert=True)
        else:
            await update.reply_text("🚫 This command is restricted to the bot owner.")
        return True
    return False
