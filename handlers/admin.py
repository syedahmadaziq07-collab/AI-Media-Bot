from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes


def _is_admin(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    return user_id in context.application.bot_data["settings"].admin_user_ids


async def add_credit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message or not _is_admin(context, update.effective_user.id):
        return
    if len(context.args) != 2:
        await update.message.reply_text("Guna: /addcredit USER_ID JUMLAH_SEN")
        return
    try:
        user_id, amount = int(context.args[0]), int(context.args[1])
        balance = await context.application.bot_data["db"].mutate_balance(
            user_id, amount, "admin_adjust", f"admin:{update.effective_user.id}"
        )
    except (ValueError, KeyError) as exc:
        await update.message.reply_text(f"Gagal: {exc}")
        return
    await update.message.reply_text(f"Baki user {user_id}: RM {balance / 100:.2f}")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message or not _is_admin(context, update.effective_user.id):
        return
    rows = await context.application.bot_data["db"].admin_stats()
    await update.message.reply_text(
        f"Users: {rows['users']}\nJobs: {rows['jobs']}\n"
        f"Completed: {rows['completed']}\nSpent: RM {rows['spent'] / 100:.2f}"
    )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message or not _is_admin(context, update.effective_user.id):
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Guna: /broadcast mesej")
        return
    ids = await context.application.bot_data["db"].all_user_ids()
    sent = 0
    for user_id in ids:
        try:
            await context.bot.send_message(user_id, text)
            sent += 1
        except Exception:
            continue
    await update.message.reply_text(f"Broadcast dihantar kepada {sent}/{len(ids)} pengguna.")


def admin_handlers():
    return [
        CommandHandler("addcredit", add_credit),
        CommandHandler("stats", stats),
        CommandHandler("broadcast", broadcast),
    ]