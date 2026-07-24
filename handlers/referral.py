from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from .common import get_services


async def show_referral(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    try:
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{update.effective_user.id}"
    except Exception:
        link = f"/start ref_{update.effective_user.id}"
    settings = context.application.bot_data["settings"]
    await update.message.reply_text(
        "Ajak kawan dan dapat bonus kredit apabila mereka mula menjana.\n\n"
        f"Link anda:\n{link}\n\n"
        f"Bonus: RM {settings.referral_bonus / 100:.2f} untuk anda dan kawan."
    )