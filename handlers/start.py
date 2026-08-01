from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from .common import build_menu_message, get_services


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    # Reset any active conversation state so the bot doesn't get confused.
    for key in ("conv_msg_id", "conv_chat_id", "job_type", "model_key",
                "selected_ratio", "prompt", "image_path"):
        context.user_data.pop(key, None)

    db, *_ = get_services(context)
    referred_by = None
    if context.args and context.args[0].startswith("ref_"):
        try:
            referred_by = int(context.args[0][4:])
        except ValueError:
            referred_by = None

    await db.upsert_user(
        update.effective_user.id,
        update.effective_user.username,
        referred_by,
    )

    text, markup = await build_menu_message(
        context, update.effective_user.id, update.effective_user.first_name
    )

    # Edit the previous welcome message in-place if it still exists,
    # otherwise send a fresh one and remember its ID.
    prev_msg_id = context.user_data.get("welcome_msg_id")
    prev_chat_id = context.user_data.get("welcome_chat_id")
    if prev_msg_id and prev_chat_id:
        try:
            await context.bot.edit_message_text(
                chat_id=prev_chat_id,
                message_id=prev_msg_id,
                text=text,
                reply_markup=markup,
            )
            return
        except Exception:
            pass  # message deleted or too old — fall through to send a new one

    msg = await update.message.reply_text(text, reply_markup=markup)
    context.user_data["welcome_msg_id"] = msg.message_id
    context.user_data["welcome_chat_id"] = msg.chat_id


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """CallbackQueryHandler for menu:back — edits the current message to show main menu."""
    if not update.callback_query or not update.effective_user:
        return
    text, markup = await build_menu_message(
        context, update.effective_user.id, update.effective_user.first_name
    )
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(text, reply_markup=markup)
