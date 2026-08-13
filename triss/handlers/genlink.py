"""
triss.handlers.genlink
=======================
Owner-only. /genlink then a single owner message -> stored in the Store
Channel, saved to MongoDB, and returned as one brand-new secure link.
Every invocation issues a new token, even for identical content.
"""

from __future__ import annotations

import logging

from pyrogram import filters
from pyrogram.types import Message

from triss.bot import app
from triss.database import models as db
from triss.services.cleanup import session_manager, session_is
from triss.services.storage import store_message, message_ref, StorageError
from triss.utils.auth import owner_filter, deny_if_not_owner
from triss.utils.keyboards import cancel_only
from triss.utils.tokens import generate_token, build_deep_link

logger = logging.getLogger("triss.handlers.genlink")


@app.on_message(filters.command("genlink") & filters.private)
async def genlink_command(client, message: Message) -> None:
    if await deny_if_not_owner(message):
        return
    session_manager.set(message.from_user.id, "genlink_waiting")
    await message.reply_text(
        "📥 Send me the message/file/text/link you want to generate a link for.",
        reply_markup=cancel_only("genlink:cancel"),
    )


@app.on_message(filters.private & owner_filter & session_is("genlink_waiting") & ~filters.command(
    ["genlink", "batch", "custombatch", "done", "cancelbatch", "broadcast", "settings", "start"]))
async def genlink_capture(client, message: Message) -> None:
    user_id = message.from_user.id
    session_manager.clear(user_id)  # one-shot: consume the session immediately

    try:
        stored = await store_message(client, message)
    except StorageError as e:
        await message.reply_text(f"⚠️ {e}")
        return

    token = generate_token()
    await db.create_link(token, "single", [message_ref(stored, 0)])

    username = getattr(client, "username", None) or (await client.get_me()).username
    link = build_deep_link(username, token)
    await message.reply_text(f"✅ Link generated:\n\n`{link}`", disable_web_page_preview=True)
