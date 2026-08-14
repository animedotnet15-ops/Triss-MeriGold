"""
triss.web.server
=================
Minimal aiohttp server exposing:

  GET /health           -> "OK" (Railway/Render liveness probe)
  GET /                 -> "OK" (same, for platforms that probe "/")
  GET /v/<session_id>   -> the shortener's own destination page (see
                            triss.services.shortener module docstring for
                            why this route exists and what it does and
                            does not prove). On success, 302-redirects the
                            browser into Telegram; on bypass/expiry/replay,
                            returns a short plain-text explanation instead
                            of ever redirecting into a delivery path.
"""

from __future__ import annotations

import logging

from aiohttp import web

from triss.config import config
from triss.services import shortener

logger = logging.getLogger("triss.web")


async def health(_request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def verify_landing(request: web.Request) -> web.Response:
    session_id = request.match_info.get("session_id", "")
    if not session_id:
        return web.Response(status=404, text="Not found.")

    outcome, deep_link, _session = await shortener.handle_landing(session_id)

    if outcome == shortener.LandingOutcome.REDIRECTED and deep_link:
        raise web.HTTPFound(location=deep_link)
    if outcome == shortener.LandingOutcome.BYPASS:
        return web.Response(
            status=403,
            text="🚨 Bypass detected — you completed this too quickly. "
                 "Go back to Telegram and tap Try Again to get a fresh link.",
        )
    elif outcome == shortener.LandingOutcome.EXPIRED:
        return web.Response(
            status=410,
            text="⏰ This verification link has expired. "
                 "Go back to Telegram and tap Try Again to get a fresh link.",
        )
    elif outcome == shortener.LandingOutcome.ALREADY_USED:
        return web.Response(status=410, text="This verification link has already been used.")
    else:
        return web.Response(status=404, text="This verification link is invalid or has expired.")


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/", health)
    app.router.add_get("/v/{session_id}", verify_landing)
    return app


async def start_web_server() -> web.AppRunner:
    aio_app = build_app()
    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=config.port)
    await site.start()
    logger.info("Web server listening on 0.0.0.0:%s (GET /health, GET /v/<session_id>).", config.port)
    return runner
  
