"""
triss.utils.validators
=======================
Small, defensive validators. Never trust raw user text before it reaches
a database query or a Telegram API call.
"""

from __future__ import annotations

import re
from typing import Optional

_CHAT_ID_RE = re.compile(r"^-?\d+$")
_TELEGRAM_FOLDER_RE = re.compile(r"^https://t\.me/addlist/[A-Za-z0-9_-]+/?$")
_TELEGRAM_INVITE_RE = re.compile(r"^https://t\.me/(\+|joinchat/)[A-Za-z0-9_-]+/?$")

# Reasonably strict but permissive host-shape check: labels of letters,
# digits and hyphens separated by dots, final label alphabetic (TLD).
_DOMAIN_RE = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.[A-Za-z]{2,63}$"
)
_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)


def is_valid_chat_id(text: str) -> bool:
    text = text.strip()
    if not _CHAT_ID_RE.match(text):
        return False
    # Telegram supergroup/channel IDs are large negative numbers (-100...)
    try:
        int(text)
    except ValueError:
        return False
    return True


def is_valid_folder_link(text: str) -> bool:
    return bool(_TELEGRAM_FOLDER_RE.match(text.strip()))


def is_valid_invite_link(text: str) -> bool:
    return bool(_TELEGRAM_INVITE_RE.match(text.strip()))


def sanitize_settings_text(text: str, max_len: int = 4096) -> str:
    """Defensive trim for any owner-supplied text destined for a settings
    field / MongoDB document. Telegram already caps message length well
    below this, this is a hard backstop."""
    return text[:max_len]


def normalize_shortener_domain(text: str) -> Optional[str]:
    """Accepts 'example.com' or 'https://example.com/' and returns a bare,
    validated host ('example.com'), or None if the input isn't a plausible
    domain. Storing the bare host (not a full URL) keeps later URL-building
    unambiguous regardless of how the owner typed it."""
    candidate = text.strip()
    candidate = re.sub(r"^https?://", "", candidate, flags=re.IGNORECASE)
    candidate = candidate.split("/", 1)[0]
    candidate = candidate.rstrip(".")
    if not candidate or len(candidate) > 253:
        return None
    if not _DOMAIN_RE.match(candidate):
        return None
    return candidate.lower()


def is_valid_url(text: str) -> bool:
    return bool(_URL_RE.match(text.strip()))


def is_valid_api_key(text: str, min_len: int = 3, max_len: int = 256) -> bool:
    candidate = text.strip()
    if len(candidate) < min_len or len(candidate) > max_len:
        return False
    if any(c.isspace() for c in candidate):
        return False
    return True
