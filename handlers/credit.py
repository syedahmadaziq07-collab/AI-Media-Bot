from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from .common import back_to_menu_button, get_services
from services.payment_service import PACKAGES


async def show_credit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    await update.callback_query.answer()
    rows = [
        [InlineKeyboardButton(f"{p.label} · {p.price_label}", callback_data=f"credit:{p.key}")]
        for p in PACKAGES
    ]
    rows.append([InlineKeyboardButton("◀️ Menu Utama", callback_data="menu:back")])
    await update.callback_query.edit_message_text(
        "Pilih pakej kredit:",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def choose_credit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    package_key = query.data.split(":", 1)[1]
    package = next((item for item in PACKAGES if item.key == package_key), None)
    if not package:
        await query.edit_message_text("Pakej tidak ditemui.", reply_markup=back_to_menu_button())
        return
    _, _, _, payment = get_services(context)
    await query.edit_message_text(
        payment.create_checkout(update.effective_user.id, package),
        reply_markup=back_to_menu_button(),
    )
