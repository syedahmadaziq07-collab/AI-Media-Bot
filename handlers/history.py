from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from models_config import MODEL_BY_KEY
from .common import get_services


def _history_text(jobs: list[dict]) -> str:
    if not jobs:
        return "Belum ada sejarah generasi."
    lines = []
    for job in jobs:
        name = MODEL_BY_KEY.get(job["model_key"])
        label = name.display_name if name else job["model_key"]
        lines.append(f"• {label} · {job['status']} · {job['created_at'][:16]}")
    return "Sejarah generasi:\n\n" + "\n".join(lines)


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    db, *_ = get_services(context)
    jobs = await db.recent_jobs(update.effective_user.id)
    await update.message.reply_text(
        _history_text(jobs),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Seterusnya", callback_data="history:next:8")]]
        ),
    )


async def history_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    offset = int(query.data.rsplit(":", 1)[-1])
    db, *_ = get_services(context)
    jobs = await db.recent_jobs(update.effective_user.id, offset=offset)
    buttons = []
    if offset >= 8:
        buttons.append(InlineKeyboardButton("Sebelumnya", callback_data=f"history:prev:{offset - 8}"))
    if len(jobs) == 8:
        buttons.append(InlineKeyboardButton("Setersusnya", callback_data=f"history:next:{offset + 8}"))
    await query.edit_message_text(
        _history_text(jobs),
        reply_markup=InlineKeyboardMarkup([buttons] if buttons else []),
    )