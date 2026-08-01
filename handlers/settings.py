from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from .common import back_to_menu_button


async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "Terima kasih. Hantar maklum balas anda dalam mesej seterusnya "
        "atau terus hubungi admin.",
        reply_markup=back_to_menu_button(),
    )


async def language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "Bahasa semasa: Bahasa Melayu.\nTetapan bahasa akan datang.",
        reply_markup=back_to_menu_button(),
    )


async def weekly_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query or not update.effective_user:
        return
    await update.callback_query.answer()
    db = context.application.bot_data["db"]
    settings = context.application.bot_data["settings"]
    if not await db.can_checkin(update.effective_user.id):
        await update.callback_query.edit_message_text(
            "Check-in anda sudah digunakan. Cuba lagi selepas 7 hari.",
            reply_markup=back_to_menu_button(),
        )
        return
    await db.set_checkin(update.effective_user.id)
    balance = await db.mutate_balance(
        update.effective_user.id, settings.checkin_bonus, "checkin_bonus", "weekly"
    )
    await update.callback_query.edit_message_text(
        f"Check-in berjaya. Bonus RM {settings.checkin_bonus / 100:.2f} diterima.\n"
        f"Baki baharu: RM {balance / 100:.2f}",
        reply_markup=back_to_menu_button(),
    )


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    await update.callback_query.answer()
    db = context.application.bot_data["db"]
    rows = await db.leaderboard()
    if not rows:
        await update.callback_query.edit_message_text(
            "Papan pendahulu belum mempunyai data.",
            reply_markup=back_to_menu_button(),
        )
        return
    lines = [
        f"{index}. @{row['username'] or row['user_id']} · {row['completed_jobs']} generasi"
        for index, row in enumerate(rows, 1)
    ]
    await update.callback_query.edit_message_text(
        "Papan Pendahulu\n\n" + "\n".join(lines),
        reply_markup=back_to_menu_button(),
    )
