"""Local development / testing entry point for JagoVideo Clone bot.

⚠️  NOT FOR PRODUCTION ⚠️
Production runs on Vercel via:
  api/telegram-webhook.py  — receives Telegram webhook updates
  api/fal-webhook.py       — receives fal.ai job completion callbacks

This script is a polling-mode convenience for local testing only.
It connects to the same Supabase database as production — be careful.

Runs two async services concurrently:
  - python-telegram-bot polling (handles all Telegram updates)
  - aiohttp HTTP server on $PORT (handles admin API endpoints)
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

import db.queries as q
from bot.handlers import (
    handle_callback,
    handle_command,
    handle_photo,
    handle_text_message,
)
from api.admin_broadcast import make_broadcast_handler

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _admin_ids() -> set[int]:
    raw = os.environ.get("ADMIN_USER_IDS", "")
    ids: set[int] = set()
    for item in raw.split(","):
        try:
            ids.add(int(item.strip()))
        except ValueError:
            pass
    return ids


async def _is_in_maintenance(user_id: int | None) -> tuple[bool, str]:
    """Return (blocked, message). Admins are never blocked."""
    if user_id and user_id in _admin_ids():
        return False, ""
    settings = await asyncio.to_thread(q.get_app_settings)
    if settings.get("maintenance_mode"):
        msg = (settings.get("maintenance_message") or "Bot dalam penyelenggaraan.").strip()
        return True, msg
    return False, ""


# ── Update handlers ────────────────────────────────────────────────────────────

async def _on_callback(update: Update, context) -> None:
    cq = update.callback_query
    if not cq:
        return
    user_id = cq.from_user.id if cq.from_user else None
    blocked, msg = await _is_in_maintenance(user_id)
    if blocked:
        await cq.answer(msg, show_alert=True)
        return
    await handle_callback(cq, context.bot)


async def _on_message(update: Update, context) -> None:
    if not update.message:
        return
    msg = update.message
    user_id = msg.from_user.id if msg.from_user else None
    blocked, maintenance_msg = await _is_in_maintenance(user_id)
    if blocked:
        await msg.reply_text(maintenance_msg)
        return
    if msg.text and msg.text.startswith("/"):
        await handle_command(msg, context.bot)
    elif msg.photo or (
        msg.document
        and msg.document.mime_type
        and msg.document.mime_type.startswith("image/")
    ):
        await handle_photo(msg, context.bot)
    elif msg.text:
        await handle_text_message(msg, context.bot)


# ── Entry point ────────────────────────────────────────────────────────────────

async def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Add it via Replit Secrets (Tools → Secrets)."
        )
    fal_key = os.environ.get("FAL_KEY", "")
    if not fal_key:
        raise RuntimeError(
            "FAL_KEY is not set. Add it via Replit Secrets (Tools → Secrets)."
        )
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set. "
            "Add them via Replit Secrets (Tools → Secrets)."
        )

    logger.warning(
        "⚠️  Running in LOCAL POLLING mode against Supabase. "
        "This is for development/testing only — production uses Vercel webhooks."
    )

    # ── Telegram bot ──────────────────────────────────────────────────────────
    ptb_app = Application.builder().token(token).build()
    ptb_app.add_handler(CallbackQueryHandler(_on_callback))
    ptb_app.add_handler(MessageHandler(filters.ALL, _on_message))

    # ── Admin HTTP server ─────────────────────────────────────────────────────
    web_app = web.Application()
    web_app.router.add_post("/api/admin-broadcast", make_broadcast_handler(ptb_app.bot))

    port = int(os.environ.get("PORT", 3000))
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)

    # ── Signal handling ───────────────────────────────────────────────────────
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # Windows

    # ── Run both services ─────────────────────────────────────────────────────
    async with ptb_app:
        await ptb_app.start()
        await ptb_app.updater.start_polling(drop_pending_updates=True)
        await site.start()
        logger.info(
            "JagoVideo Clone bot started (polling, LOCAL DEV). "
            "Admin API listening on port %d.", port
        )

        await stop_event.wait()  # block until SIGTERM / SIGINT

        logger.info("Shutting down…")
        await runner.cleanup()
        await ptb_app.updater.stop()
        await ptb_app.stop()


if __name__ == "__main__":
    asyncio.run(main())
