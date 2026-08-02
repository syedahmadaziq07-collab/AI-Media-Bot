"""Admin broadcast endpoint.

Local polling (bot.py): make_broadcast_handler(bot) returns an aiohttp handler.
Vercel serverless:      class handler(BaseHTTPRequestHandler) handles POST + OPTIONS.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path when Vercel imports this as a function.
sys.path.insert(0, str(Path(__file__).parent.parent))

import db.queries as q

logger = logging.getLogger(__name__)

_CONCURRENCY = 20  # max simultaneous Telegram sends (~30 msg/s Telegram limit)

# CORS headers returned on every response (preflight and actual).
_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Admin-Secret",
}


# ── Shared broadcast logic ─────────────────────────────────────────────────────

async def do_broadcast(bot: Any, message: str) -> dict:
    """Send *message* to every user. Returns {success, sent_count, failed_count}."""
    user_ids: list[int] = await asyncio.to_thread(q.all_user_ids)
    semaphore = asyncio.Semaphore(_CONCURRENCY)
    sent = 0
    failed = 0

    async def _send(uid: int) -> None:
        nonlocal sent, failed
        async with semaphore:
            try:
                await bot.send_message(uid, message)
                sent += 1
            except Exception as exc:
                failed += 1
                logger.debug("Broadcast to %d failed: %s", uid, exc)

    await asyncio.gather(*[_send(uid) for uid in user_ids])

    await asyncio.to_thread(q.log_broadcast, message, sent, failed)
    logger.info("Broadcast complete — sent=%d failed=%d total=%d", sent, failed, len(user_ids))
    return {"success": True, "sent_count": sent, "failed_count": failed}


# ── aiohttp handler (bot.py local polling) ─────────────────────────────────────

def make_broadcast_handler(bot: Any):
    """Return an aiohttp request handler bound to *bot* (used by bot.py)."""
    from aiohttp import web

    expected_secret = os.environ.get("ADMIN_BROADCAST_SECRET", "")

    async def _handler(request: web.Request) -> web.Response:
        cors = dict(_CORS_HEADERS)

        # CORS preflight
        if request.method == "OPTIONS":
            return web.Response(status=204, headers=cors)

        # Auth
        provided = request.headers.get("X-Admin-Secret", "")
        if not expected_secret or provided != expected_secret:
            return web.json_response({"error": "Unauthorized"}, status=401, headers=cors)

        # Parse body
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400, headers=cors)

        message = (body.get("message") or "").strip()
        if not message:
            return web.json_response({"error": "'message' is required"}, status=400, headers=cors)

        result = await do_broadcast(bot, message)
        return web.json_response(result, headers=cors)

    return _handler


# ── Vercel serverless handler ──────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    """Vercel serverless handler for /api/admin_broadcast."""

    def _send_cors_preflight(self) -> None:
        """Respond to OPTIONS preflight with 204 + CORS headers."""
        self.send_response(204)
        for key, value in _CORS_HEADERS.items():
            self.send_header(key, value)
        self.end_headers()

    def _send_json(self, status: int, body: dict) -> None:
        """Write a JSON response with CORS headers."""
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        for key, value in _CORS_HEADERS.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle CORS preflight requests from the dashboard browser."""
        self._send_cors_preflight()

    def do_POST(self) -> None:  # noqa: N802
        """Handle broadcast POST requests from the dashboard."""
        from dotenv import load_dotenv
        load_dotenv()

        expected_secret = os.environ.get("ADMIN_BROADCAST_SECRET", "")
        provided = self.headers.get("X-Admin-Secret", "")
        if not expected_secret or provided != expected_secret:
            self._send_json(401, {"error": "Unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._send_json(400, {"error": "Invalid JSON"})
            return

        message = (body.get("message") or "").strip()
        if not message:
            self._send_json(400, {"error": "'message' is required"})
            return

        try:
            from telegram import Bot
            token = os.environ["TELEGRAM_BOT_TOKEN"]

            async def _run() -> dict:
                async with Bot(token=token) as bot:
                    return await do_broadcast(bot, message)

            result = asyncio.run(_run())
            self._send_json(200, result)
        except Exception:
            print("[ERROR] admin_broadcast handler failed:", flush=True)
            print(traceback.format_exc(), flush=True)
            self._send_json(500, {"error": "Broadcast failed"})

    def log_message(self, format, *args):  # noqa: A002
        pass  # suppress default access logs
