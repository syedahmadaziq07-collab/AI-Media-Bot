"""Vercel serverless function — receives fal.ai job completion callbacks."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import db.queries as q
import services.credit_service as credit
from services.fal_service import extract_output_url
from db.queries import utc_now

logger = logging.getLogger(__name__)


async def _deliver(job: dict, bot_token: str) -> None:
    """Send the finished (or failed) job result to the user via Telegram.

    Uses 'async with Bot(...)' to ensure the underlying HTTPX session is
    properly closed after delivery (fix #9 — no resource leak).
    """
    from telegram import Bot
    from telegram.constants import ParseMode
    from bot.keyboards import back_to_menu_markup, money

    user_id = int(job["user_id"])
    job_type = job.get("job_type", "video")

    async with Bot(token=bot_token) as bot:
        if job["status"] == "completed" and job.get("output_url"):
            caption = (
                f"✅ Generasi siap!\n"
                f"Model: {job['model_key']}\n"
                f"Job ID: <code>{job['id'][:8]}</code>"
            )
            try:
                if job_type == "video":
                    await bot.send_video(
                        user_id, job["output_url"], caption=caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=back_to_menu_markup(),
                    )
                else:
                    await bot.send_photo(
                        user_id, job["output_url"], caption=caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=back_to_menu_markup(),
                    )
            except Exception as exc:
                logger.error("Failed to deliver result for job %s: %s", job["id"], exc)
                # Fall back to sending the URL as plain text
                try:
                    await bot.send_message(
                        user_id,
                        f"✅ Generasi siap! Tapi gagal hantar fail.\nURL: {job['output_url']}",
                        reply_markup=back_to_menu_markup(),
                    )
                except Exception:
                    pass
        else:
            try:
                await bot.send_message(
                    user_id,
                    f"❌ Generasi gagal untuk job <code>{job['id'][:8]}</code>. "
                    "Kredit telah dipulangkan.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_to_menu_markup(),
                )
            except Exception as exc:
                logger.error("Failed to notify failure for job %s: %s", job["id"], exc)


async def _process(data: dict, bot_token: str) -> None:
    """Handle fal.ai webhook payload.

    All q.* and credit.* calls are synchronous (Supabase client), so they are
    dispatched via asyncio.to_thread() to avoid blocking the event loop (fix #8).

    The job dict is updated locally after each DB write to avoid a second
    round-trip to Supabase (fix — no double q.get_job()) .
    """
    request_id = data.get("request_id") or data.get("requestId")
    status = data.get("status", "")
    payload = data.get("payload") or data.get("result") or {}

    if not request_id:
        logger.warning("fal webhook: missing request_id in payload: %s", json.dumps(data)[:300])
        return

    # ── Look up the job by fal request_id ─────────────────────────────────────
    job = await asyncio.to_thread(q.get_job_by_fal_request, request_id)
    if not job:
        logger.warning("fal webhook: unknown fal_request_id=%s", request_id)
        return

    job_id = job["id"]
    now = utc_now()

    # ── Update job status and optionally refund ────────────────────────────────
    if status == "completed":
        output_url = extract_output_url(payload, job["job_type"])
        if output_url:
            await asyncio.to_thread(
                q.update_job, job_id,
                status="completed", output_url=output_url, completed_at=now,
            )
            # Update local dict — no second DB round-trip needed
            job = {**job, "status": "completed", "output_url": output_url}
        else:
            logger.error(
                "fal webhook: completed but no URL found for job %s — payload: %s",
                job_id, json.dumps(payload)[:500],
            )
            await asyncio.to_thread(q.update_job, job_id, status="failed", completed_at=now)
            job = {**job, "status": "failed"}
            await asyncio.to_thread(
                credit.refund, int(job["user_id"]), int(job["cost"]), f"refund:{job_id}"
            )
    else:
        # status == "error" / "failed" / anything unexpected
        logger.warning("fal webhook: job %s arrived with status=%r", job_id, status)
        await asyncio.to_thread(q.update_job, job_id, status="failed", completed_at=now)
        job = {**job, "status": "failed"}
        await asyncio.to_thread(
            credit.refund, int(job["user_id"]), int(job["cost"]), f"refund:{job_id}"
        )

    await _deliver(job, bot_token)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            token = os.environ["TELEGRAM_BOT_TOKEN"]
            asyncio.run(_process(data, token))
        except Exception as exc:
            print(f"[fal-webhook] Error: {exc}", flush=True)

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass
