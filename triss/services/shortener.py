"""
triss.services.shortener
=========================
Shortener provider adapter + per-access verification state machine.

--------------------------------------------------------------------------
THE VULNERABILITY THIS MODULE FIXES, AND HOW
--------------------------------------------------------------------------
The previous design generated a verification session and pointed the
shortener directly at `https://t.me/<bot>?start=verify_<session_id>`,
then decided VERIFIED/BYPASS/EXPIRED purely from server-side elapsed
time since session creation. That is insufficient: `session_id` is
unguessable, but ONCE an attacker has it (e.g. by extracting the
shortener's true destination with an automated redirect-resolver instead
of actually sitting through the shortener's ads/timers), elapsed time is
trivially fakeable — the attacker just sleeps `minimum_seconds` and then
opens the deep link. Nothing about that deep link is bound to the act of
actually reaching the far end of the shortener flow.

The fix: the shortener is no longer pointed at the Telegram deep link at
all. It is pointed at our OWN web server, at
`{PUBLIC_BASE_URL}/v/<session_id>` (triss/web/server.py). Landing on that
route is the one event that (a) can only legitimately happen once the
shortener has released its redirect, and (b) is entirely under our
control server-side. When that route is hit, we atomically transition
the session CREATED -> REDIRECTED, mint a fresh single-use random proof,
store only its SHA-256 hash (never the raw value), and 302-redirect the
browser to `https://t.me/<bot>?start=verify_<session_id>.<proof>`. Only a
request carrying the *correct* proof for that *specific* session can ever
move it to VERIFIED. A guessed/predicted/replayed `verify_<session_id>`
with no proof, or a wrong proof, is rejected outright — it never falls
back to trusting elapsed time alone.

--------------------------------------------------------------------------
PROVIDER-SIDE COMPLETION VERIFICATION (mandatory, separate layer)
--------------------------------------------------------------------------
The `/v/<session_id>` redirect-plus-signed-proof mechanism above proves
only that the browser reached our own endpoint after *some* redirect
chain released it. That is NOT proof the shortener's flow — ads,
countdown, whatever the provider actually gates on — was completed. It
is retained as one required layer (it stops "guess/predict the deep
link" and replay attacks), but it is never, by itself, sufficient to
mark a session VERIFIED.

Genuine completion evidence can only come from the provider itself:
a verification API call, a signed callback, a provider-issued
completion token, or another server-to-server check — see
`ShortenerProvider.verify_completion()`. A provider only qualifies by
setting `supports_completion_verification = True` and overriding
`verify_completion()` to perform a real check; the base class defaults
to `False`/"cannot verify", which is intentionally fail-closed rather
than optimistic.

`evaluate_verification()` requires ALL of: valid one-time proof for
this exact session, elapsed time within [minimum, maximum], AND a
provider that both claims and successfully performs genuine completion
verification. Missing any one of those results in no delivery — never
a fallback to the others alone. If the configured provider cannot
genuinely verify completion (the case for the bundled
`GenericQueryProvider` — see its own docstring for why, e.g. VPLinks),
or for any provider whose settings changed after a session was
created, the session is failed closed into `PROVIDER_UNAVAILABLE` and
nothing is delivered.

LINK GENERATION and COMPLETION VERIFICATION are deliberately two
separate capabilities, gated independently:
  - `generate_short_link()` / `start_new_verification()` only require a
    working provider (real domain + API key that can actually shorten a
    URL). They do NOT require `supports_completion_verification` — a
    provider without it still produces a real, working shortened link,
    and Settings -> Shortener -> Test / the enable toggle exercise this
    exact call so the owner sees a genuine success or a genuine error,
    never a fabricated one (see `test_provider` and
    `triss/handlers/callbacks.py`).
  - `evaluate_verification()` alone is the delivery gate, and it alone
    checks `provider_supports_verification()`. A provider without it
    can still hand out real short links and take a user through its
    whole redirect flow, but the resulting session can never progress
    past `REDIRECTED` — it fails closed into `PROVIDER_UNAVAILABLE`
    every time, so no content is ever delivered through this path
    until a provider with genuine completion verification is
    configured. This is intentional, not a bug: Shortener can be
    "enabled" (and generate real links) with such a provider, but its
    delivery gate honestly never opens.
--------------------------------------------------------------------------
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import quote, urlparse

import aiohttp

from triss.config import config
from triss.database import models as db
from triss.utils.tokens import generate_token

logger = logging.getLogger("triss.shortener")

HTTP_TIMEOUT_SECONDS = 12


# ---------------------------------------------------------------------------
# Session state machine
# ---------------------------------------------------------------------------

class SessionState:
    CREATED = "created"        # session minted, shortener link handed to the user
    REDIRECTED = "redirected"  # user's browser reached our own /v/<id> landing route
    VERIFIED = "verified"      # correct, timely proof AND genuine provider-side
                                # completion confirmation were both presented
    CONSUMED = "consumed"      # VERIFIED session has been used to deliver content (terminal)
    BYPASS = "bypass"          # completed faster than minimum_time (terminal)
    EXPIRED = "expired"        # exceeded maximum_time before verification (terminal)
    INVALID = "invalid"        # missing/incorrect proof, or unknown session (terminal)
    FAILED = "failed"          # provider/internal error prevented verification (terminal)
    PROVIDER_UNAVAILABLE = "provider_unavailable"  # the configured provider cannot
                                # (or no longer can) genuinely attest completion —
                                # terminal, fail-closed, never delivers (terminal)


class VerificationOutcome:
    NOT_FOUND = "not_found"
    ALREADY_USED = "already_used"
    INVALID_PROOF = "invalid_proof"
    BYPASS = "bypass"
    EXPIRED = "expired"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
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


def _generate_raw_proof() -> str:
    return secrets.token_urlsafe(24)


def build_verification_deep_link(bot_username: str, session_id: str, raw_proof: str) -> str:
    return f"https://t.me/{bot_username}?start=verify_{session_id}.{raw_proof}"


def parse_verify_payload(payload: str) -> tuple[Optional[str], Optional[str]]:
    """payload is everything after 'verify_'. Returns (session_id, proof),
    either of which is None if the payload doesn't have the expected
    '<session_id>.<proof>' shape (e.g. a legacy/forged payload with no
    proof at all) — callers must treat a None proof as automatically
    invalid, never as "skip the proof check"."""
    if not payload or "." not in payload:
        return (payload or None), None
    session_id, _, proof = payload.partition(".")
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

    Every provider must implement `shorten`. Genuine completion
    verification is opt-in and off by default: a provider is only
    trusted to attest completion if it BOTH sets
    `supports_completion_verification = True` AND overrides
    `verify_completion()` with a real check (a provider verification
    API call, validating a signed callback already recorded on the
    session, exchanging/validating a provider-issued completion token,
    or any other genuine server-to-server mechanism). Do not override
    either half without the other — a provider that claims support but
    doesn't truly check anything (or vice versa) defeats the point.

    The base-class defaults (`supports_completion_verification = False`,
    `verify_completion()` returns False) are deliberately fail-closed:
    "no known way to verify" must never be treated as "verified", and
    callers (`evaluate_verification`, `generate_short_link`, and the
    Shortener enable-toggle) all key off `supports_completion_verification`
    to refuse to proceed rather than silently trusting an unverifiable
    provider.
    """

    #: Set to True only on a subclass whose `verify_completion()` performs
    #: a genuine, provider-attested check. Never set True speculatively.
    supports_completion_verification: bool = False

    def __init__(self, domain: str, api_key: str) -> None:
        self.domain = domain
        self.api_key = api_key

    @abstractmethod
    async def shorten(self, long_url: str) -> str:
        """Returns the shortened URL. Raises a ProviderError subclass on
        any failure — never returns a guessed/partial/fabricated URL."""

    async def verify_completion(self, session: dict) -> bool:
        """Must return True ONLY when this specific session's shortener
        flow has been genuinely, provider-side confirmed as completed
        (e.g. via a signed callback payload already stored on `session`,
        a live provider API/status call keyed on a `provider_ref` stored
        on `session`, or a validated provider-issued completion token).
        Only ever called when `supports_completion_verification` is True.
        The base implementation always returns False — it exists so a
        misconfigured subclass fails closed instead of raising, but no
        subclass should rely on inheriting it; a provider that supports
        verification must override this with real logic, not this
        default."""
        return False


class GenericQueryProvider(ShortenerProvider):
    """Adapter for the AdLinkFly-family "Developers API" convention:

        GET https://<domain>/api?api=<key>&url=<url>

    VPLinks — the provider actually configured in this deployment — runs
    this same widely-cloned engine (as do GPLinks, several other
    "monetized shortener" sites, etc). Per that API's own documentation,
    a successful call returns JSON of the shape:

        {"status":"success","shortenedUrl":"https://<domain>/xxxxx"}

    and an unsuccessful one returns a JSON error body (commonly
    `{"status":"error","message":"..."}`, field names vary slightly
    between clones). Some other generic-shortener deployments that reuse
    this same query convention instead return the bare short URL as
    plain text with no JSON wrapper at all. This adapter accepts either
    of those two *documented* shapes and nothing else — it does not
    guess at undocumented fields.

    This is a bare redirect-generation call: the provider gives back a
    short URL and nothing else. There is no verification API, callback,
    or completion token anywhere in this documented API, so it genuinely
    cannot attest completion — `supports_completion_verification` stays
    False and `verify_completion` is intentionally left un-overridden
    (the fail-closed base behavior is correct here, not a gap to paper
    over). If you integrate a different provider that DOES expose a real
    verification mechanism, add a new `ShortenerProvider` subclass for
    it rather than changing this one."""

    supports_completion_verification = False

    async def shorten(self, long_url: str) -> str:
        parsed = urlparse(long_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ProviderInvalidResponse("Refusing to shorten a malformed long_url.")

        endpoint = f"https://{self.domain}/api?api={quote(self.api_key)}&url={quote(long_url, safe='')}"
        try:
            timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(endpoint) as resp:
                    if resp.status == 429:
                        raise ProviderRateLimited("Shortener provider rate-limited us (HTTP 429).")
                    if resp.status in (401, 403):
                        raise ProviderUnavailable(f"Shortener provider rejected credentials (HTTP {resp.status}).")
                    if resp.status != 200:
                        raise ProviderUnavailable(f"Shortener provider returned HTTP {resp.status}.")
                    raw = (await resp.text()).strip()
        except ProviderError:
            raise
        except TimeoutError as exc:
            raise ProviderTimeout("Shortener provider request timed out.") from exc
        except aiohttp.ClientError as exc:
            raise ProviderUnavailable(f"Shortener provider network error: {exc}") from exc

        if not raw:
            raise ProviderInvalidResponse("Shortener provider returned an empty response.")

        short_url = self._parse_response(raw)
        parsed_result = urlparse(short_url)
        if parsed_result.scheme not in ("http", "https") or not parsed_result.netloc:
            raise ProviderInvalidResponse("Shortener provider returned a malformed short URL.")
        return short_url

    @staticmethod
    def _parse_response(raw: str) -> str:
        """Parses only the two documented response shapes for this API
        convention — never guesses at an undocumented field name."""
        if raw.startswith("{") or raw.startswith("["):
            try:
                data = json.loads(raw)
            except (ValueError, TypeError) as exc:
                raise ProviderInvalidResponse(
                    f"Shortener provider returned malformed JSON: {exc}"
                ) from exc
            if not isinstance(data, dict):
                raise ProviderInvalidResponse("Shortener provider returned an unexpected JSON shape.")

            status = data.get("status")
            if status is not None and str(status).lower() != "success":
                message = data.get("message") or data.get("error") or "unspecified error"
                raise ProviderInvalidResponse(f"Shortener provider reported an error: {message}")

            short_url = data.get("shortenedUrl") or data.get("shortened_url")
            if not short_url or not isinstance(short_url, str):
                raise ProviderInvalidResponse(
                    "Shortener provider returned success with no 'shortenedUrl' field."
                )
            return short_url.strip()

        # Not JSON at all: some deployments of this same query convention
        # return the bare short URL as plain text — accept that too.
        return raw


def get_provider(shortener_settings: dict) -> Optional[ShortenerProvider]:
    domain = shortener_settings.get("domain")
    api_key = shortener_settings.get("api_key")
    if not domain or not api_key:
        return None
    # Single provider implementation today (VPLinks / AdLinkFly-family
    # API); this factory is the extension point for a provider-specific
    # adapter (see class docstrings above).
    return GenericQueryProvider(domain, api_key)


def provider_supports_verification(shortener_settings: dict) -> bool:
    """Single source of truth for 'can this configuration ever produce a
    genuinely verifiable session'. Used to fail closed both when the
    owner tries to enable Shortener and, defensively, inside
    `evaluate_verification` — see module docstring."""
    provider = get_provider(shortener_settings)
    return provider is not None and provider.supports_completion_verification


async def generate_short_link(shortener_settings: dict, long_url: str) -> Optional[str]:
    """Calls the configured provider's real `shorten()` API and returns the
    resulting short URL, or None if the call itself failed (bad domain/key,
    network error, malformed response, etc).

    LINK GENERATION and COMPLETION VERIFICATION are deliberately separate
    capabilities (see module docstring and `ShortenerProvider`): this
    function only performs link generation, and does so regardless of
    whether the provider can also genuinely attest completion. A session
    created from a provider without `supports_completion_verification`
    still gets a real, working shortened link here — it simply can never
    progress past `REDIRECTED` in `evaluate_verification()`, which is the
    one and only place completion is (or isn't) trusted, and which fails
    closed into `PROVIDER_UNAVAILABLE` independently of this function. See
    `provider_supports_verification()` for that separate, delivery-gating
    check."""
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


_TEST_TARGET_URL = "https://telegram.org/"


async def test_provider(shortener_settings: dict) -> tuple[bool, str]:
    """Owner-facing 'Test' action (Settings -> Shortener -> Test): makes one
    real call to the configured provider's `shorten()` API against a fixed,
    harmless target URL and reports the actual outcome. Never reports
    success without a successful provider response, and never invents a
    URL — the returned message either contains the real short URL the
    provider handed back, or the real error the provider/network raised."""
    provider = get_provider(shortener_settings)
    if provider is None:
        return False, "Set a Domain and API key first."
    try:
        short_url = await provider.shorten(_TEST_TARGET_URL)
    except ProviderRateLimited as exc:
        return False, f"Rate limited by provider: {exc}"
    except ProviderTimeout as exc:
        return False, f"Provider timed out: {exc}"
    except ProviderUnavailable as exc:
        return False, f"Provider unavailable: {exc}"
    except ProviderInvalidResponse as exc:
        return False, f"Invalid provider response: {exc}"
    except ProviderError as exc:
        return False, f"Unexpected provider error: {exc}"
    return True, short_url


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
    session_id = generate_token()

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
    """Server-side evaluation of the `/start verify_<session_id>.<proof>`
    deep link. Trusts nothing from the client except the two opaque
    strings, both checked against the stored, hashed session record:
    a missing/incorrect proof is REJECTED outright, regardless of timing —
    elapsed time is never sufficient on its own (see module docstring)."""
    session = await db.get_verification_session(session_id)
    if session is None:
        return VerificationOutcome.NOT_FOUND, None

    if session["verification_status"] not in (SessionState.REDIRECTED,):
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

    # Mandatory, separate layer: genuine provider-side completion evidence.
    # The proof + timing checks above only establish that the browser
    # reached our own /v/<session_id> endpoint within the allowed window —
    # never treat that alone as "the shortener flow was completed" (see
    # module docstring). Re-fetch current settings/provider here (rather
    # than trusting anything cached from session creation) so a provider
    # downgraded or reconfigured mid-flow can never slip through.
    current_settings = await db.get_settings()
    current_shortener_settings = current_settings.get("shortener", {})
    provider = get_provider(current_shortener_settings)
    if not provider_supports_verification(current_shortener_settings):
        updated = await db.transition_verification_session(
            session_id, [SessionState.REDIRECTED], SessionState.PROVIDER_UNAVAILABLE
        )
        return VerificationOutcome.PROVIDER_UNAVAILABLE, updated or session

    try:
        provider_confirmed = await provider.verify_completion(session)
    except Exception:
        logger.exception("Provider completion verification raised for session %s.", session_id)
        provider_confirmed = False

    if not provider_confirmed:
        updated = await db.transition_verification_session(
            session_id, [SessionState.REDIRECTED], SessionState.PROVIDER_UNAVAILABLE
        )
        return VerificationOutcome.PROVIDER_UNAVAILABLE, updated or session

    updated = await db.transition_verification_session(
        session_id, [SessionState.REDIRECTED], SessionState.VERIFIED, extra_set={"completed_at": now}
    )
    if updated is None:
        # Lost a race to a concurrent duplicate callback — do not deliver.
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
