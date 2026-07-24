from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from .common import get_services, main_keyboard, money
from models_config import MODELS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    db, *_ = get_services(context)
    referred_by = None
    if context.args and context.args[0].startswith("ref_"):
        try:
            referred_by = int(context.args[0][4:])
        except ValueError:
            referred_by = None
    user = await db.upsert_user(
        update.effective_user.id,
        update.effective_user.username,
        referred_by,
    )
    stats = await db.user_stats(update.effective_user.id)
    groups: dict[str, list[str]] = {}
    for model in MODELS:
        groups.setdefault(model.server_group, []).append(model.display_name)
    model_text = "\n".join(
        f"• {group}: {', '.join(names)}" for group, names in groups.items()
    )
    await update.message.reply_text(
        f"Selamat datang ke JagoVideo Clone, {update.effective_user.first_name}.\n\n"
        f"Baki kredit: {money(int(user['balance']))}\n"
        f"Generasi: {stats['completed']} siap / {stats['total']} jumlah\n\n"
        f"Model tersedia:\n{model_text}\n\n"
        "Pilih apa yang anda mahu buat di menu.",
        reply_markup=main_keyboard(),
    )


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Menu utama dibuka. Gunakan butang di bawah.",
        )
        await update.callback_query.message.reply_text(
            "Apa yang anda mahu buat?",
            reply_markup=main_keyboard(),
        )