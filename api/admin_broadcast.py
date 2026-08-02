"""Admin broadcast logic — called by the HTTP endpoint in bot.py."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import db.queries as q

logger = logging.getLogger(__name__)

_CONCURRENCY = 20  # max simultaneous Telegram sends (~30 msg/s Telegram limit)


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


def make_broadcast_handler(bot: Any):
    """Return an aiohttp request handler bound to *bot*."""
    from aiohttp import web

    expected_secret = os.environ.get("ADMIN_BROADCAST_SECRET", "")

    async def handler(request: web.Request) -> web.Response:
        # Auth
        provided = request.headers.get("X-Admin-Secret", "")
        if not expected_secret or provided != expected_secret:
            return web.json_response({"error": "Unauthorized"}, status=401)

        # Parse body
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        message = (body.get("message") or "").strip()
        if not message:
            return web.json_response({"error": "'message' is required"}, status=400)

        result = await do_broadcast(bot, message)
        return web.json_response(result)

    return handler
