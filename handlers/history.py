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


def _history_markup(offset: int, has_more: bool) -> InlineKeyboardMarkup:
    nav = []
    if offset >= 8:
        nav.append(InlineKeyboardButton("Sebelumnya", callback_data=f"history:prev:{offset - 8}"))
    if has_more:
        nav.append(InlineKeyboardButton("Seterusnya", callback_data=f"history:next:{offset + 8}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton("◀️ Menu Utama", callback_data="menu:back")])
    return InlineKeyboardMarkup(rows)


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query or not update.effective_user:
        return
    await update.callback_query.answer()
    db, *_ = get_services(context)
    jobs = await db.recent_jobs(update.effective_user.id)
    await update.callback_query.edit_message_text(
        _history_text(jobs),
        reply_markup=_history_markup(offset=0, has_more=len(jobs) == 8),
    )


async def history_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    offset = int(query.data.rsplit(":", 1)[-1])
    db, *_ = get_services(context)
    jobs = await db.recent_jobs(update.effective_user.id, offset=offset)
    await query.edit_message_text(
        _history_text(jobs),
        reply_markup=_history_markup(offset=offset, has_more=len(jobs) == 8),
    )
