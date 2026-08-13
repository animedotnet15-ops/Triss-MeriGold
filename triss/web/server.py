"""
triss.web.server
=================
aiohttp server exposing:

  GET /health          -> "OK" (Railway/Render liveness probe)
  GET /v/<session_id>   -> shortener verification landing route

The /v/ route is the destination the Shortener is configured to point
at (see triss.services.shortener for why: reaching this route, server
-side, is the one event a completion proof can honestly be minted from).
It never renders anything sensitive and never leaks internals — on
success it 302-redirects straight into Telegram; on any failure it shows
a minimal, generic page and logs the detail server-side only.
"""

from __future__ import annotations

import logging

from aiohttp import web

from triss.config import config

logger = logging.getLogger("triss.web")

_FAILURE_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Triss</title></head><body style="font-family:sans-serif;text-align:center;padding:40px">
<p>{message}</p><p>Please return to Telegram and try again.</p></body></html>"""


async def health(_request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def verify_landing(request: web.Request) -> web.Response:
    from triss.services import shortener

    session_id = request.match_info.get("session_id", "")
    if not session_id or len(session_id) > 128:
        return web.Response(text=_FAILURE_PAGE.format(message="Invalid link."), content_type="text/html", status=400)

    try:
        outcome, deep_link, _session = await shortener.handle_landing(session_id)
    except Exception:
        logger.exception("Unexpected error in /v/%s landing handler.", session_id)
        return web.Response(
            text=_FAILURE_PAGE.format(message="Something went wrong."), content_type="text/html", status=500
        )

    if outcome == shortener.LandingOutcome.REDIRECTED and deep_link:
        raise web.HTTPFound(deep_link)
    if outcome == shortener.LandingOutcome.BYPASS:
        message = "Verification was completed too quickly and was flagged."
    elif outcome == shortener.LandingOutcome.EXPIRED:
        message = "This verification link expired."
    elif outcome == shortener.LandingOutcome.ALREADY_USED:
        message = "This verification link was already used."
    else:
        message = "This verification link is invalid."
    return web.Response(text=_FAILURE_PAGE.format(message=message), content_type="text/html", status=200)


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
    logger.info("Health server listening on 0.0.0.0:%s (GET /health).", config.port)
    return runner
