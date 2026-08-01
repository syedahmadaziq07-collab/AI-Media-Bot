from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from .common import back_to_menu_button, get_services, money


async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query or not update.effective_user:
        return
    await update.callback_query.answer()
    db, *_ = get_services(context)
    user = await db.get_user(update.effective_user.id)
    transactions = await db.recent_transactions(update.effective_user.id)
    lines = [
        f"{item['created_at'][:10]} · {item['type']} · "
        f"{'+' if item['amount'] >= 0 else ''}{money(int(item['amount']))}"
        for item in transactions
    ]
    await update.callback_query.edit_message_text(
        f"Baki semasa: {money(int(user['balance']))}\n\n"
        "Transaksi terakhir:\n" + ("\n".join(lines) or "Belum ada transaksi."),
        reply_markup=back_to_menu_button(),
    )
