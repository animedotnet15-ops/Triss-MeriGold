"""
triss.utils.formatting
=======================
Default text templates (small-caps aesthetic, per spec) and the
{mention}/{first}/{last}/{username}/{id} variable substitution used in
the welcome message.
"""

from __future__ import annotations

from typing import Optional

DEFAULT_WELCOME_TEXT = (
    "╭━━━〔 🦋 ʜᴇʟʟᴏ, {mention} 〕━━━╮\n"
    "\n"
    "💜 ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴛʀɪss 🌸\n"
    "\n"
    "🌷 ʏᴏᴜ'ᴠᴇ ᴊᴜsᴛ ᴇɴᴛᴇʀᴇᴅ ʏᴏᴜʀ ʟɪᴛᴛʟᴇ ғɪʟᴇ ᴜɴɪᴠᴇʀsᴇ. ☁️\n"
    "\n"
    "📨 ʏᴏᴜ ʙʀɪɴɢ ᴛʜᴇ ғɪʟᴇ...\n"
    "🧚 ᴛʀɪss ᴛᴜʀɴs ɪᴛ ɪɴᴛᴏ sᴏᴍᴇᴛʜɪɴɢ sʜᴀʀᴀʙʟᴇ.\n"
    "\n"
    "╭───────────────╮\n"
    "\n"
    "🎀 ᴅʀᴏᴘ ɪᴛ ʜᴇʀᴇ\n"
    "🌐 ɢᴇᴛ ʏᴏᴜʀ ʟɪɴᴋ\n"
    "🪄 sʜᴀʀᴇ ɪᴛ ᴀɴʏᴡʜᴇʀᴇ\n"
    "\n"
    "╰───────────────╯\n"
    "\n"
    "🍃 ɴᴏ ᴄᴏᴍᴘʟɪᴄᴀᴛɪᴏɴs.\n"
    "🚀 ɴᴏ ᴜɴɴᴇᴄᴇssᴀʀʏ sᴛᴇᴘs.\n"
    "💠 ᴊᴜsᴛ ғɪʟᴇs → ʟɪɴᴋs → sʜᴀʀᴇ.\n"
    "\n"
    "╰━━━〔 🐇 ʜᴀᴠᴇ ғᴜɴ ᴡɪᴛʜ ᴛʀɪss! 〕━━━╯"
)

MAINTENANCE_TEXT = (
    "🧑\u200d🔧 ᴛʀɪss ɪs ᴄᴜʀʀᴇɴᴛʟʏ ᴜɴᴅᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ.\n\n"
    "ᴘʟᴇᴀsᴇ ᴄʜᴇᴄᴋ ʙᴀᴄᴋ sʜᴏʀᴛʟʏ. ✨"
)

FORCE_SUB_TEXT = (
    "📢 ᴊᴏɪɴ ᴏᴜʀ ᴄʜᴀɴɴᴇʟ ✨\n\n"
    "🔔 ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ ᴜsɪɴɢ ᴛʀɪss ғɪʟᴇ ᴠᴀᴜʟᴛ, ᴘʟᴇᴀsᴇ ᴊᴏɪɴ ᴛʜᴇ ʀᴇǫᴜɪʀᴇᴅ ᴄʜᴀɴɴᴇʟ(s) ʙᴇʟᴏᴡ. 🌐\n\n"
    "🌐 ᴏɴᴄᴇ ʏᴏᴜ'ᴠᴇ ᴊᴏɪɴᴇᴅ, ᴛᴀᴘ ᴄʜᴇᴄᴋ ᴊᴏɪɴᴇᴅ ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ. ✅"
)

AUTO_DELETE_NOTICE_TEXT = (
    "🗑️ ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ ✨\n\n"
    "📩 ᴛʜɪs ᴍᴇssᴀɢᴇ ᴡɪʟʟ ʙᴇ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ᴅᴇʟᴇᴛᴇᴅ ᴀғᴛᴇʀ ᴛʜᴇ ᴄᴏɴғɪɢᴜʀᴇᴅ ᴛɪᴍᴇ ⏳\n\n"
    "🆘 ᴘʟᴇᴀsᴇ sᴀᴠᴇ ʏᴏᴜʀ ғɪʟᴇ ʙᴇғᴏʀᴇ ᴛʜᴇ ᴛɪᴍᴇ ʟɪᴍɪᴛ. ✦"
)

LINK_EXPIRED_TEXT = (
    "⌛ ᴛʜɪs ʟɪɴᴋ ʜᴀs ᴇxᴘɪʀᴇᴅ.\n\n"
    "ᴘʟᴇᴀsᴇ ʀᴇǫᴜᴇsᴛ ᴀ ɴᴇᴡ ʟɪɴᴋ ғʀᴏᴍ ᴛʜᴇ ᴏᴡɴᴇʀ. 🔁"
)

LINK_INVALID_TEXT = (
    "❌ ᴛʜɪs ʟɪɴᴋ ɪs ɪɴᴠᴀʟɪᴅ ᴏʀ ʜᴀs ʙᴇᴇɴ ʀᴇᴠᴏᴋᴇᴅ."
)

SHORTENER_VERIFY_TEXT = (
    "🪻ᴛʀɪss ғɪʟᴇ ᴠᴀᴜʟᴛ ⟡ ʏᴏᴜʀ ғɪʟᴇ ɪs ʀᴇᴀᴅʏ ᴛᴏ ᴀᴄᴄᴇss.\n\n"
    "ʙᴇғᴏʀᴇ ɢᴇᴛᴛɪɴɢ ᴛʜᴇ ғɪʟᴇ, ᴘʟᴇᴀsᴇ ᴄᴏᴍᴘʟᴇᴛᴇ ᴛʜᴇ sʜᴏʀᴛᴇɴᴇʀ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ 🧸.\n\n"
    "ʏᴏᴜ ʜᴀᴠᴇ ᴛʜᴇ ᴄᴏɴғɪɢᴜʀᴇᴅ ᴛɪᴍᴇ ⌛ ᴛᴏ ᴄᴏᴍᴘʟᴇᴛᴇ ɪᴛ.\n\n"
    "ɪғ ʏᴏᴜ ᴅᴏɴ'ᴛ ᴠᴇʀɪғʏ ᴡɪᴛʜɪɴ ᴛʜᴇ ᴛɪᴍᴇ ʟɪᴍɪᴛ, ᴛʜᴇ ʟɪɴᴋ ᴡɪʟʟ ᴇxᴘɪʀᴇ 🫧.\n\n"
    "ᴏɴᴄᴇ ᴠᴇʀɪғɪᴇᴅ, ʏᴏᴜʀ ғɪʟᴇ ᴡɪʟʟ ʙᴇ ᴅᴇʟɪᴠᴇʀᴇᴅ ɪᴍᴍᴇᴅɪᴀᴛᴇʟʏ 🪽"
)

SHORTENER_BYPASS_TEXT = (
    "🚨 ʙʏᴘᴀss ᴅᴇᴛᴇᴄᴛᴇᴅ!\n\n"
    "⟡ ᴛʜᴇ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ᴡᴀs ᴄᴏᴍᴘʟᴇᴛᴇᴅ ᴛᴏᴏ ǫᴜɪᴄᴋʟʏ. 🛑\n\n"
    "ᴘʟᴇᴀsᴇ ᴜsᴇ ᴛʜᴇ ᴏʀɪɢɪɴᴀʟ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ʟɪɴᴋ ᴀɴᴅ ᴄᴏᴍᴘʟᴇᴛᴇ ᴛʜᴇ ᴘʀᴏᴄᴇss ᴘʀᴏᴘᴇʀʟʏ."
)

SHORTENER_EXPIRED_TEXT = (
    "⏰ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ʟɪɴᴋ ᴇxᴘɪʀᴇᴅ.\n\n"
    "🫧 ᴛʜɪs ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ sᴇssɪᴏɴ ʜᴀs ᴇxᴘɪʀᴇᴅ."
)

SHORTENER_RATE_LIMITED_TEXT = (
    "🚫 ᴛᴏᴏ ᴍᴀɴʏ ғᴀɪʟᴇᴅ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ᴀᴛᴛᴇᴍᴘᴛs.\n\n"
    "ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ ᴀ ғᴇᴡ ᴍɪɴᴜᴛᴇs ʙᴇғᴏʀᴇ ᴛʀʏɪɴɢ ᴀɢᴀɪɴ."
)

SHORTENER_SESSION_INVALID_TEXT = (
    "❌ ᴛʜɪs ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ sᴇssɪᴏɴ ɪs ɪɴᴠᴀʟɪᴅ ᴏʀ ᴀʟʀᴇᴀᴅʏ ᴜsᴇᴅ.\n\n"
    "Pʟᴇᴀsᴇ ʀᴇᴏᴘᴇɴ ᴛʜᴇ ᴏʀɪɢɪɴᴀʟ ᴄᴏɴᴛᴇɴᴛ ʟɪɴᴋ ᴛᴏ sᴛᴀʀᴛ ᴀ ɴᴇᴡ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ."
)

SHORTENER_UNAVAILABLE_TEXT = (
    "⚠️ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ɪs ᴛᴇᴍᴘᴏʀᴀʀɪʟʏ ᴜɴᴀᴠᴀɪʟᴀʙʟᴇ. Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ sʜᴏʀᴛʟʏ."
)


def mask_secret(value: Optional[str], visible: int = 4) -> str:
    """Never echo a full API token back to the owner. Shows only the last
    `visible` characters, per spec's `••••••••1234` example."""
    if not value:
        return "Not set"
    if len(value) <= visible:
        return "•" * len(value)
    return "•" * 8 + value[-visible:]


def render_welcome(template: Optional[str], *, user_id: int, first_name: str,
                    last_name: Optional[str] = None, username: Optional[str] = None) -> str:
    text = template or DEFAULT_WELCOME_TEXT
    mention = f"[{first_name}](tg://user?id={user_id})"
    return (
        text.replace("{mention}", mention)
            .replace("{first}", first_name or "")
            .replace("{last}", last_name or "")
            .replace("{username}", f"@{username}" if username else "")
            .replace("{id}", str(user_id))
    )
