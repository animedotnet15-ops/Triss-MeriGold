"""
triss.utils.tokens
===================
Secure, unguessable token generation for share links, plus helpers to
build/parse the Telegram deep link (`t.me/<bot>?start=<token>`).

Tokens are generated with `secrets.token_urlsafe`, which uses the OS
CSPRNG. They never encode the MongoDB ObjectId, the storage channel ID,
or the storage message ID — those stay server-side only.

--------------------------------------------------------------------------
DEEP-LINK LENGTH BUDGET — READ BEFORE CHANGING ANY TOKEN SIZE
--------------------------------------------------------------------------
Telegram hard-caps the entire `?start=` payload at 64 characters
(A-Z, a-z, 0-9, `_`, `-` only) — see
https://core.telegram.org/bots/features#deep-linking. A payload over
that limit is not a soft warning: Telegram apps silently fail to carry
the parameter through the deep link, so the bot receives a bare
`/start` with no payload at all. That failure mode is invisible from
inside the bot (no exception, no log, nothing in `message.command`),
which made it a very easy latent bug to ship.

A plain content token (`generate_token()`) is used standalone as the
whole `?start=<token>` payload, so its whole 64-char budget is its own.
`SESSION_ID_BYTES` in `triss.services.shortener` is a *different,
smaller* budget because that token has to share the 64 chars with the
literal `verify_` prefix, a `.` separator, AND a second random proof
token in the same payload (`verify_<session_id>.<proof>`) — see the
budget comment next to `SESSION_ID_BYTES` there before changing either
size.
"""

from __future__ import annotations

import secrets

TOKEN_BYTES = 24  # -> 32 url-safe base64 characters, ~192 bits of entropy.
# Safe standalone: this is the *entire* "?start=<token>" payload for a
# genlink/batch/custombatch content link (no prefix, no sibling token),
# so 32 chars leaves comfortable room under Telegram's 64-char cap.


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
