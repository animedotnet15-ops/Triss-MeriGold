"""
triss.services.shortener
=========================
Shortener provider adapter + per-access verification state machine.

--------------------------------------------------------------------------
WHAT THIS MODULE ACTUALLY VERIFIES — READ BEFORE RELYING ON THIS
--------------------------------------------------------------------------
The shortener is pointed at THIS bot's own web server
(`{PUBLIC_BASE_URL}/v/<session_id>`, see triss/web/server.py), not
directly at a `t.me` deep link. Reaching that route is the one event
that (a) can only legitimately happen once the shortener has released
its redirect, and (b) is entirely under our control server-side — so it
is also the moment the single-use proof is minted (only its hash is
ever stored). Only after that does the browser get bounced into
Telegram, at `https://t.me/<bot>?start=verify_<session_id><proof>`.

The bot then checks, entirely server-side:

  1. The `(session_id, proof)` pair matches exactly one REDIRECTED
     session (a guessed/forged/replayed payload is rejected outright).
  2. `elapsed = now - created_at` is >= the configured Minimum Time.
  3. `elapsed` is <= the configured Maximum Time.

If all three hold, the session moves REDIRECTED -> VERIFIED.

What this DOES protect against: guessing/predicting another user's
session, replaying an already-used verification, using a session created
for a different Telegram user, tampering with the proof, and concurrent/
duplicate delivery of the same session — AND, because the shortener's
own destination is our landing route rather than the raw deep link, a
user (or script) extracting the *final* Telegram destination straight
out of the shortener's redirect chain without ever visiting it gains
nothing: that destination doesn't exist until the landing route itself
has been hit and minted it.

What this does NOT and cannot protect against: it cannot confirm the
shortener's own page/ad/task content was genuinely engaged with (read,
watched, clicked) — only that the browser's redirect chain passed
through both the shortener and our landing route within the configured
time window. Genuine content-completion evidence would additionally
require real provider-side confirmation (a verification API, signed
callback, or completion token — see `ShortenerProvider.verify_completion()`,
kept here as an unused extension point in case a real provider adapter
is added later). This module and every caller must keep describing this
as time-window-plus-redirect gating, never as "verified" in the sense of
proven ad/content engagement.
--------------------------------------------------------------------------
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import quote, urlparse

import aiohttp

from triss.config import config
from triss.database import models as db

logger = logging.getLogger("triss.shortener")

HTTP_TIMEOUT_SECONDS = 12


# ---------------------------------------------------------------------------
# Session state machine
# ---------------------------------------------------------------------------

class SessionState:
    CREATED = "created"        # session minted, shortener link handed to the user
    REDIRECTED = "redirected"  # user's browser reached our own /v/<id> landing route;
                                # single-use proof minted at this point
    VERIFIED = "verified"      # correct proof presented within [minimum_time, maximum_time]
                                # of creation — see module docstring for exactly what this proves
    CONSUMED = "consumed"      # VERIFIED session has been used to deliver content (terminal)
    BYPASS = "bypass"          # opened faster than minimum_time (terminal)
    EXPIRED = "expired"        # exceeded maximum_time before verification (terminal)
    INVALID = "invalid"        # missing/incorrect proof, or unknown session (terminal)
    FAILED = "failed"          # internal error prevented verification (terminal)


class VerificationOutcome:
    NOT_FOUND = "not_found"
    ALREADY_USED = "already_used"
    INVALID_PROOF = "invalid_proof"
    BYPASS = "bypass"
    EXPIRED = "expired"
    VERIFIED = "verified"


class LandingOutcome:
    """Outcomes for handle_landing() — deliberately distinct from
    VerificationOutcome so 'the browser reached our landing route' can
    never be confused with 'the Telegram deep-link proof was validated'."""
    NOT_FOUND = "not_found"
    ALREADY_USED = "already_used"
    BYPASS = "bypass"
    EXPIRED = "expired"
    REDIRECTED = "redirected"


# --- per-user rate limiting for repeated invalid (bypass/expired/forged) attempts --
_FAILURE_WINDOW_SECONDS = 600
_FAILURE_THRESHOLD = 5
_failure_log: dict[int, list[float]] = {}


def record_failed_attempt(user_id: int) -> None:
    now = time.time()
    attempts = [t for t in _failure_log.get(user_id, []) if now - t < _FAILURE_WINDOW_SECONDS]
    attempts.append(now)
    _failure_log[user_id] = attempts


def is_rate_limited(user_id: int) -> bool:
    now = time.time()
    attempts = [t for t in _failure_log.get(user_id, []) if now - t < _FAILURE_WINDOW_SECONDS]
    _failure_log[user_id] = attempts
    return len(attempts) >= _FAILURE_THRESHOLD


def clear_failures(user_id: int) -> None:
    _failure_log.pop(user_id, None)


# ---------------------------------------------------------------------------
# Proof generation / verification (single-use, hashed at rest)
# ---------------------------------------------------------------------------

def _hash_proof(session_id: str, raw_proof: str) -> str:
    """Binds the proof to its session id so a hash lifted from one session's
    document could never validate a different session, even under a hash
    collision in the (unrealistic) worst case. Uses the deployment's
    VERIFICATION_SECRET as an HMAC key so the stored hash cannot be
    recomputed by anyone without server-side config access either."""
    mac = hmac.new(config.verification_secret.encode(), digestmod=hashlib.sha256)
    mac.update(session_id.encode())
    mac.update(b"|")
    mac.update(raw_proof.encode())
    return mac.hexdigest()


SESSION_ID_BYTES = 12  # -> 16 url-safe base64 characters, ~96 bits of entropy.
PROOF_BYTES = 18       # -> 24 url-safe base64 characters, ~144 bits of entropy.
# --------------------------------------------------------------------
# DEEP-LINK CHARSET + LENGTH — see triss/utils/tokens.py module
# docstring for the full budget explanation.
#
# The verification start payload is "verify_<session_id><proof>" with
# session_id and proof concatenated DIRECTLY, no separator character.
# This is deliberate: Telegram's deep-link start parameter officially
# allows only A-Z, a-z, 0-9, "_" and "-" (see
# https://core.telegram.org/bots/features#deep-linking). A "." (or any
# other) separator is outside that set and is not something Telegram
# apps are documented to guarantee passing through intact. Since both
# `secrets.token_urlsafe(SESSION_ID_BYTES)` and
# `secrets.token_urlsafe(PROOF_BYTES)` produce a FIXED length for a
# fixed byte count (base64's padding depends only on `nbytes % 3`, never
# on the random content), the two can be safely concatenated with no
# separator and split back apart later purely by position — see
# `parse_verify_payload` below.
#
# Telegram also hard-caps the whole "?start=" payload at 64 characters
# and silently drops the parameter entirely if it's longer (no error, no
# log — the bot just receives a bare "/start"). The budget here:
#     len("verify_")=7 + session_id(16) + proof(24) = 47
# which stays safely under 64 with margin to spare, while keeping both
# tokens' entropy far beyond what's brute-forceable.
_START_PARAM_MAX_LENGTH = 64  # Telegram's hard limit — do not change.


def _generate_raw_proof() -> str:
    return secrets.token_urlsafe(PROOF_BYTES)


def generate_session_id() -> str:
    return secrets.token_urlsafe(SESSION_ID_BYTES)


# Both are fixed-length for a fixed byte count (see comment above) — used
# to split the concatenated payload back apart with no separator needed.
_SESSION_ID_LENGTH = len(generate_session_id())
_PROOF_LENGTH = len(_generate_raw_proof())


def build_verification_deep_link(bot_username: str, session_id: str, raw_proof: str) -> str:
    start_param = f"verify_{session_id}{raw_proof}"
    if len(start_param) > _START_PARAM_MAX_LENGTH:
        # This must never trigger in normal operation — it exists purely
        # as a loud, fail-fast canary so this exact class of bug (silent
        # deep-link truncation) can never again ship unnoticed. Raising
        # here (instead of silently truncating or proceeding) means a
        # regression surfaces immediately as a visible error instead of
        # as "verification/delivery mysteriously doesn't work".
        raise ValueError(
            f"Verification deep-link payload is {len(start_param)} chars "
            f"(session_id={len(session_id)}, proof={len(raw_proof)}); "
            f"Telegram's start-parameter limit is {_START_PARAM_MAX_LENGTH}."
        )
    return f"https://t.me/{bot_username}?start={start_param}"


def parse_verify_payload(payload: str) -> tuple[Optional[str], Optional[str]]:
    """payload is everything after 'verify_'. Returns (session_id, proof),
    either of which is None if the payload doesn't have the expected
    fixed-length `<session_id><proof>` shape (e.g. a legacy/forged/
    truncated payload) — callers must treat a None proof as automatically
    invalid, never as "skip the proof check". Split by fixed position, not
    a separator character — see the length-budget comment above for why
    session_id/proof are guaranteed fixed-length."""
    if not payload or len(payload) != _SESSION_ID_LENGTH + _PROOF_LENGTH:
        return (payload or None), None
    session_id = payload[:_SESSION_ID_LENGTH]
    proof = payload[_SESSION_ID_LENGTH:]
    if not session_id or not proof:
        return None, None
    return session_id, proof


# ---------------------------------------------------------------------------
# Shortener provider adapter
# ---------------------------------------------------------------------------

class ProviderError(Exception):
    """Base class for every way a shortener provider call can fail. Never
    caught silently — always results in `short_url = None` upstream, never
    a fabricated URL."""


class ProviderTimeout(ProviderError):
    pass


class ProviderRateLimited(ProviderError):
    pass


class ProviderUnavailable(ProviderError):
    pass


class ProviderInvalidResponse(ProviderError):
    pass


class ShortenerProvider(ABC):
    """Adapter interface.

    Every provider must implement `shorten`. `supports_completion_verification`
    / `verify_completion()` are an UNUSED extension point in the current
    flow (see module docstring — Shortener here does redirect-plus-time-
    window gating only, not provider-side completion verification) kept so
    a real provider adapter can be wired in later without redesigning this
    interface. If you do wire one in, only set
    `supports_completion_verification = True` on a subclass whose
    `verify_completion()` performs a genuine check (a provider
    verification API call, validating a signed callback, exchanging/
    validating a provider-issued completion token, etc) — never set it
    True speculatively, and never treat the base class's `False`/"cannot
    verify" default as "verified".
    """

    #: Set to True only on a subclass whose `verify_completion()` performs
    #: a genuine, provider-attested check. Never set True speculatively.
    #: Currently unused by `evaluate_verification()` — see module docstring.
    supports_completion_verification: bool = False

    def __init__(self, domain: str, api_key: str) -> None:
        self.domain = domain
        self.api_key = api_key

    @abstractmethod
    async def shorten(self, long_url: str) -> str:
        """Returns the shortened URL. Raises a ProviderError subclass on
        any failure — never returns a guessed/partial/fabricated URL."""

    async def verify_completion(self, session: dict) -> bool:
        """Unused by the current flow (see module docstring). Kept for a
        future provider adapter: must return True ONLY when this specific
        session's shortener flow has been genuinely, provider-side
        confirmed as completed. The base implementation always returns
        False."""
        return False


class GenericQueryProvider(ShortenerProvider):
    """The widely-shared `GET https://<domain>/api?api=<key>&url=<url>&format=text`
    convention used by most drop-in shortener services. This is a bare
    redirect-generation call: the provider gives back a short URL and
    nothing else — no verification API, no callback, no completion
    token. `supports_completion_verification` stays False (accurately —
    this provider genuinely cannot attest completion) but that capability
    isn't required by the current time-window-gating flow. If you
    integrate a specific provider that DOES expose a real verification
    mechanism, add a new `ShortenerProvider` subclass for it rather than
    changing this one."""

    supports_completion_verification = False

    async def shorten(self, long_url: str) -> str:
        parsed = urlparse(long_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ProviderInvalidResponse("Refusing to shorten a malformed long_url.")

        endpoint = f"https://{self.domain}/api?api={quote(self.api_key)}&url={quote(long_url, safe='')}&format=text"
        try:
            timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(endpoint) as resp:
                    if resp.status == 429:
                        raise ProviderRateLimited(f"Shortener provider rate-limited us (HTTP 429).")
                    if resp.status in (401, 403):
                        raise ProviderUnavailable(f"Shortener provider rejected credentials (HTTP {resp.status}).")
                    if resp.status != 200:
                        raise ProviderUnavailable(f"Shortener provider returned HTTP {resp.status}.")
                    text = (await resp.text()).strip()
        except ProviderError:
            raise
        except TimeoutError as exc:
            raise ProviderTimeout("Shortener provider request timed out.") from exc
        except aiohttp.ClientError as exc:
            raise ProviderUnavailable(f"Shortener provider network error: {exc}") from exc

        if not text:
            raise ProviderInvalidResponse("Shortener provider returned an empty response.")
        parsed_result = urlparse(text)
        if parsed_result.scheme not in ("http", "https") or not parsed_result.netloc:
            raise ProviderInvalidResponse("Shortener provider returned a malformed short URL.")
        return text


def get_provider(shortener_settings: dict) -> Optional[ShortenerProvider]:
    domain = shortener_settings.get("domain")
    api_key = shortener_settings.get("api_key")
    if not domain or not api_key:
        return None
    # Single provider implementation today; this factory is the extension
    # point for a provider-specific adapter (see class docstrings above).
    return GenericQueryProvider(domain, api_key)


def provider_supports_verification(shortener_settings: dict) -> bool:
    """Whether this configuration's provider claims genuine completion
    verification. Currently unused by `evaluate_verification()` or the
    Shortener enable-toggle (redirect-plus-time-window gating only — see
    module docstring); kept for a future provider adapter to use."""
    provider = get_provider(shortener_settings)
    return provider is not None and provider.supports_completion_verification


async def generate_short_link(shortener_settings: dict, long_url: str) -> Optional[str]:
    provider = get_provider(shortener_settings)
    if provider is None:
        logger.error("Shortener is enabled but no provider is configured (missing domain/API key).")
        return None
    try:
        return await provider.shorten(long_url)
    except ProviderRateLimited as exc:
        logger.warning("Shortener provider rate limit: %s", exc)
        return None
    except ProviderTimeout as exc:
        logger.warning("Shortener provider timeout: %s", exc)
        return None
    except ProviderUnavailable as exc:
        logger.warning("Shortener provider unavailable: %s", exc)
        return None
    except ProviderInvalidResponse as exc:
        logger.warning("Shortener provider returned an invalid response: %s", exc)
        return None
    except ProviderError:
        logger.exception("Unexpected shortener provider error.")
        return None


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

async def start_new_verification(bot_username: str, user_id: int, access_token: str,
                                  shortener_settings: dict) -> tuple[Optional[dict], Optional[str]]:
    """Creates a brand-new CREATED session and its shortened landing link
    (`{PUBLIC_BASE_URL}/v/<session_id>`, NOT the raw deep link — see module
    docstring). Returns (session_doc, short_url); short_url is None if the
    provider call or configuration failed — callers must treat that as
    'verification unavailable', never silently deliver the file."""
    minimum_seconds = int(shortener_settings.get("minimum_seconds", 0))
    maximum_seconds = int(shortener_settings.get("maximum_seconds", 0))
    session_id = generate_session_id()

    session = await db.create_verification_session(
        user_id=user_id,
        access_token=access_token,
        session_id=session_id,
        minimum_seconds=minimum_seconds,
        maximum_seconds=maximum_seconds,
    )

    if not config.public_base_url:
        logger.error("Cannot start shortener verification: PUBLIC_BASE_URL is not configured.")
        return session, None

    landing_url = f"{config.public_base_url}/v/{session_id}"
    short_url = await generate_short_link(shortener_settings, landing_url)
    return session, short_url


async def handle_landing(session_id: str) -> tuple[str, Optional[str], Optional[dict]]:
    """
    Called by the web server when a browser reaches `/v/<session_id>` —
    i.e. the shortener has released its redirect. Atomically consumes the
    CREATED state (so this landing route itself can only ever be
    meaningfully hit once per session — a replayed/duplicated hit finds no
    matching document and is rejected, which also gives us the
    concurrent-request protection required for this step).

    Returns (outcome, deep_link_or_None, session_or_None) where outcome is
    one of LandingOutcome.{NOT_FOUND, BYPASS, EXPIRED, ALREADY_USED, REDIRECTED}.
    """
    session = await db.get_verification_session(session_id)
    if session is None:
        return LandingOutcome.NOT_FOUND, None, None

    now = time.time()
    elapsed = now - session["created_at"]

    if elapsed < session["minimum_time"]:
        updated = await db.transition_verification_session(
            session_id, [SessionState.CREATED], SessionState.BYPASS
        )
        return LandingOutcome.BYPASS, None, updated or session

    if elapsed > session["maximum_time"]:
        updated = await db.transition_verification_session(
            session_id, [SessionState.CREATED], SessionState.EXPIRED
        )
        return LandingOutcome.EXPIRED, None, updated or session

    raw_proof = _generate_raw_proof()
    proof_hash = _hash_proof(session_id, raw_proof)
    updated = await db.transition_verification_session(
        session_id,
        [SessionState.CREATED],
        SessionState.REDIRECTED,
        extra_set={"redirected_at": now, "proof_hash": proof_hash},
    )
    if updated is None:
        # Someone/something already consumed the CREATED state (replay of
        # this exact landing route) — never mint a second proof for it.
        current = await db.get_verification_session(session_id)
        return LandingOutcome.ALREADY_USED, None, current

    from triss.bot import app as _app  # local import: avoids a bot<->shortener import cycle
    bot_username = getattr(_app, "username", None) or (await _app.get_me()).username
    deep_link = build_verification_deep_link(bot_username, session_id, raw_proof)
    return LandingOutcome.REDIRECTED, deep_link, updated


async def evaluate_verification(session_id: str, proof: Optional[str]) -> tuple[str, Optional[dict]]:
    """Server-side evaluation of the `/start verify_<session_id><proof>`
    deep link. Trusts nothing from the client except the two opaque
    strings, both checked against the stored, hashed session record —
    a missing/incorrect proof is REJECTED outright, regardless of timing."""
    session = await db.get_verification_session(session_id)
    if session is None:
        return VerificationOutcome.NOT_FOUND, None

    if session["verification_status"] != SessionState.REDIRECTED:
        # Anything other than "freshly redirected, awaiting proof" is
        # either already resolved (VERIFIED/CONSUMED/BYPASS/EXPIRED) or
        # never legitimately redirected at all (still CREATED, or
        # INVALID/FAILED) — in every case, this is not a fresh, deliverable
        # verification.
        return VerificationOutcome.ALREADY_USED, session

    if not proof or not session.get("proof_hash"):
        await db.transition_verification_session(session_id, [SessionState.REDIRECTED], SessionState.INVALID)
        return VerificationOutcome.INVALID_PROOF, session

    expected_hash = session["proof_hash"]
    candidate_hash = _hash_proof(session_id, proof)
    if not hmac.compare_digest(expected_hash, candidate_hash):
        await db.transition_verification_session(session_id, [SessionState.REDIRECTED], SessionState.INVALID)
        return VerificationOutcome.INVALID_PROOF, session

    # Defense in depth: re-check the timing bounds at this second
    # checkpoint too (in addition to the check already done in
    # handle_landing), using nothing but the server clock.
    now = time.time()
    elapsed = now - session["created_at"]

    if elapsed < session["minimum_time"]:
        updated = await db.transition_verification_session(session_id, [SessionState.REDIRECTED], SessionState.BYPASS)
        return VerificationOutcome.BYPASS, updated or session

    if elapsed > session["maximum_time"]:
        updated = await db.transition_verification_session(session_id, [SessionState.REDIRECTED], SessionState.EXPIRED)
        return VerificationOutcome.EXPIRED, updated or session

    # Atomic transition filtered on the current status — this is also the
    # replay/concurrency guard: only the single request that wins this
    # update may treat the session as VERIFIED. A duplicate/concurrent
    # /start update for the same session finds no matching document and
    # is rejected as ALREADY_USED.
    updated = await db.transition_verification_session(
        session_id, [SessionState.REDIRECTED], SessionState.VERIFIED, extra_set={"completed_at": now}
    )
    if updated is None:
        current = await db.get_verification_session(session_id)
        return VerificationOutcome.ALREADY_USED, current
    return VerificationOutcome.VERIFIED, updated


async def consume_session(session_id: str) -> Optional[dict]:
    """Atomically moves VERIFIED -> CONSUMED. Only the single caller that
    receives a non-None result may proceed to deliver content — this is
    the replay-protection / concurrent-delivery guard: a session can fund
    exactly one delivery, ever, no matter how many /start updates or
    duplicate callbacks arrive for it."""
    return await db.transition_verification_session(
        session_id, [SessionState.VERIFIED], SessionState.CONSUMED, extra_set={"consumed_at": time.time()}
    )
