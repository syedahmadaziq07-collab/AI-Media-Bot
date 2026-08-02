"""Vercel serverless function — receives Telegram webhook updates."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# Ensure project root is on the import path when running as a Vercel function.
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from telegram import Bot, Update
from bot.handlers import (
    handle_callback,
    handle_command,
    handle_photo,
    handle_text_message,
)
import db.queries as q


async def _process(data: dict, token: str) -> None:
    try:
        async with Bot(token=token) as bot:
            update = Update.de_json(data, bot)
            user_id = update.effective_user.id if update.effective_user else None

            # ── Maintenance mode check ────────────────────────────────────────
            # Must happen BEFORE any routing so ALL update types are blocked.
            # Fail-safe: if fetching settings fails, bot continues normally.
            print(f"[MAINT-DEBUG] Checking maintenance for user_id={user_id}", flush=True)
            try:
                settings = await asyncio.to_thread(q.get_app_settings)
                print(f"[MAINT-DEBUG] maintenance_mode={settings.get('maintenance_mode')}, admin_chat_id_raw={settings.get('admin_chat_id')!r}", flush=True)

                if settings.get("maintenance_mode"):
                    # Build admin set: app_settings.admin_chat_id (live, DB)
                    # merged with ADMIN_USER_IDS env var (fallback).
                    admin_ids: set[int] = set()
                    for raw in [
                        settings.get("admin_chat_id") or "",
                        os.environ.get("ADMIN_USER_IDS", ""),
                    ]:
                        for item in raw.split(","):
                            try:
                                admin_ids.add(int(item.strip()))
                            except (ValueError, AttributeError):
                                pass

                    print(f"[MAINT-DEBUG] parsed admin_ids={admin_ids}, user_id in admin_ids={user_id in admin_ids if user_id is not None else False}", flush=True)
                    is_admin = bool(user_id and user_id in admin_ids)

                    if not is_admin:
                        maintenance_msg = (
                            settings.get("maintenance_message")
                            or "Bot sedang dalam penyelenggaraan. Sila cuba lagi kemudian."
                        ).strip()
                        if update.callback_query:
                            await update.callback_query.answer(
                                text=maintenance_msg, show_alert=True
                            )
                        elif update.message:
                            await bot.send_message(update.message.chat_id, maintenance_msg)
                        return  # stop — no further routing
            except Exception:
                # Log but never let a settings-fetch failure crash the webhook.
                print("[WARN] maintenance check failed — continuing normally:", flush=True)
                print(traceback.format_exc(), flush=True)
            # ─────────────────────────────────────────────────────────────────

            if update.callback_query:
                print(f"[DEBUG] Callback query received: data={update.callback_query.data!r}", flush=True)
                await handle_callback(update.callback_query, bot)

            elif update.message:
                msg = update.message
                if msg.text and msg.text.startswith("/"):
                    await handle_command(msg, bot)
                elif msg.photo or (msg.document and msg.document.mime_type and
                                   msg.document.mime_type.startswith("image/")):
                    await handle_photo(msg, bot)
                elif msg.text:
                    await handle_text_message(msg, bot)
    except BaseException:
        print("[ERROR] _process raised an exception:", flush=True)
        print(traceback.format_exc(), flush=True)
        raise


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        start_time = time.time()
        print("[DEBUG] do_POST called — webhook handler started", flush=True)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            token = os.environ["TELEGRAM_BOT_TOKEN"]
            asyncio.run(_process(data, token))
            print(f"[DEBUG] do_POST total time: {time.time() - start_time:.2f}s", flush=True)
        except BaseException:
            # Always return 200 so Telegram doesn't retry infinitely.
            print(f"[ERROR] Unhandled exception in do_POST after {time.time() - start_time:.2f}s:", flush=True)
            print(traceback.format_exc(), flush=True)

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):  # suppress default access logs
        pass
