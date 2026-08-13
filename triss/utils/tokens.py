"""
triss.utils.tokens
===================
Secure, unguessable token generation for share links, plus helpers to
build/parse the Telegram deep link (`t.me/<bot>?start=<token>`).

Tokens are generated with `secrets.token_urlsafe`, which uses the OS
CSPRNG. They never encode the MongoDB ObjectId, the storage channel ID,
or the storage message ID — those stay server-side only.
"""

from __future__ import annotations

import secrets

TOKEN_BYTES = 24  # -> 32 url-safe base64 characters, ~192 bits of entropy


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def build_deep_link(bot_username: str, token: str) -> str:
    return f"https://t.me/{bot_username}?start={token}"


def is_plausible_token(candidate: str) -> bool:
    """Cheap shape check before hitting the database — rejects obviously
    malformed input without leaking anything about valid tokens."""
    if not candidate or not isinstance(candidate, str):
        return False
    if len(candidate) < 16 or len(candidate) > 128:
        return False
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    return all(c in allowed for c in candidate)
