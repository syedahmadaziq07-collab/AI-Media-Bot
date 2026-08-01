"""Vercel serverless function — receives Telegram webhook updates."""

from __future__ import annotations

import asyncio
import json
import os
import sys
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


async def _process(data: dict, token: str) -> None:
    bot = Bot(token=token)
    update = Update.de_json(data, bot)

    if update.callback_query:
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


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            token = os.environ["TELEGRAM_BOT_TOKEN"]
            asyncio.run(_process(data, token))
        except Exception as exc:
            # Always return 200 so Telegram doesn't retry infinitely.
            print(f"[telegram-webhook] Error: {exc}", flush=True)

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):  # suppress default access logs
        pass
