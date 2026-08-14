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
        # NOT a bare 302. After a chain of redirects (shortener page -> ad
        # network -> this route), many mobile browsers silently refuse to
        # follow a server-side redirect straight into an external app
        # (Telegram) — they only honor a hand-off triggered by a real tap.
        # A blind web.HTTPFound() here can appear to "do nothing" even
        # though this route worked perfectly and logged correctly.
        # Serve a real page instead: try the automatic redirect for
        # browsers that do allow it, AND always show a big tappable
        # fallback link that works everywhere, every time.
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="0; url={deep_link}">
<title>Opening Telegram…</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background:#111; color:#eee;
          display:flex; flex-direction:column; align-items:center;
          justify-content:center; height:100vh; margin:0; text-align:center; }}
  a.btn {{ margin-top:24px; padding:16px 28px; background:#2AABEE; color:#fff;
           border-radius:12px; text-decoration:none; font-size:18px; font-weight:600; }}
</style></head>
<body>
  <p>Verified ✅ Opening Telegram…</p>
  <a class="btn" href="{deep_link}">Tap here if it doesn't open automatically</a>
  <script>window.location.replace("{deep_link}");</script>
</body></html>"""
        return web.Response(text=html, content_type="text/html")
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

  
