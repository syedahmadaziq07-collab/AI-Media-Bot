from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes


async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "Terima kasih. Hantar maklum balas anda dalam mesej seterusnya "
            "atau terus hubungi admin."
        )


async def language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("Bahasa semasa: Bahasa Melayu.\nTetapan bahasa akan datang.")


async def weekly_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    db = context.application.bot_data["db"]
    settings = context.application.bot_data["settings"]
    if not await db.can_checkin(update.effective_user.id):
        await update.message.reply_text("Check-in anda sudah digunakan. Cuba lagi selepas 7 hari.")
        return
    await db.set_checkin(update.effective_user.id)
    balance = await db.mutate_balance(
        update.effective_user.id, settings.checkin_bonus, "checkin_bonus", "weekly"
    )
    await update.message.reply_text(
        f"Check-in berjaya. Bonus RM {settings.checkin_bonus / 100:.2f} diterima.\n"
        f"Baki baharu: RM {balance / 100:.2f}"
    )


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    db = context.application.bot_data["db"]
    rows = await db.leaderboard()
    if not rows:
        await update.message.reply_text("Papan pendahulu belum mempunyai data.")
        return
    lines = [
        f"{index}. @{row['username'] or row['user_id']} · {row['completed_jobs']} generasi"
        for index, row in enumerate(rows, 1)
    ]
    await update.message.reply_text("Papan Pendahulu\n\n" + "\n".join(lines))