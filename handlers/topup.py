"""Top-up flow: receipt upload by user → admin manual approval.

States:
  AWAIT_RECEIPT — waiting for user to send a payment receipt photo.

Entry:  CallbackQueryHandler  topup:receipt:<request_id>
Cancel: CallbackQueryHandler  topup:cancel:<request_id>   (fallback + global)
Admin:  CallbackQueryHandler  admin:approve:<request_id>
         CallbackQueryHandler  admin:reject:<request_id>
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .common import back_to_menu_button, build_menu_message, get_services

AWAIT_RECEIPT = 20


def _is_admin(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    return user_id in context.application.bot_data["settings"].admin_user_ids


# ── Entry: user taps "📤 Hantar Resit Pembayaran" ─────────────────────────────

async def request_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    request_id = query.data.split("topup:receipt:", 1)[1]
    context.user_data["topup_request_id"] = request_id
    await query.edit_message_text(
        "📤 Sila hantar screenshot atau gambar resit pembayaran anda.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Batalkan", callback_data=f"topup:cancel:{request_id}")],
        ]),
    )
    return AWAIT_RECEIPT


# ── AWAIT_RECEIPT: user sends a photo ─────────────────────────────────────────

async def receive_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.effective_user:
        return AWAIT_RECEIPT

    image = update.message.photo[-1] if update.message.photo else update.message.document
    if not image:
        await update.message.reply_text("⚠️ Sila hantar gambar resit (foto atau dokumen imej).")
        return AWAIT_RECEIPT

    request_id = context.user_data.get("topup_request_id")
    if not request_id:
        return ConversationHandler.END

    db, *_ = get_services(context)

    try:
        req = await db.get_topup_request(request_id)
    except KeyError:
        await update.message.reply_text("⚠️ Permintaan tidak ditemui. Sila mulakan semula.")
        context.user_data.pop("topup_request_id", None)
        return ConversationHandler.END

    if req["status"] != "awaiting_receipt":
        await update.message.reply_text("⚠️ Permintaan ini sudah diproses atau tamat tempoh.")
        context.user_data.pop("topup_request_id", None)
        return ConversationHandler.END

    file_id = image.file_id
    await db.update_topup_request(request_id, receipt_file_id=file_id, status="pending_review")

    await update.message.reply_text(
        "✅ Resit diterima. Permintaan anda sedang disemak oleh admin.\n"
        "Anda akan dimaklumkan sebaik sahaja disahkan.",
        reply_markup=back_to_menu_button(),
    )

    # Notify admin
    settings = context.application.bot_data["settings"]
    admin_chat_id = settings.admin_chat_id
    if admin_chat_id:
        try:
            pkg = await db.get_credit_package(req["package_id"])
            user = await db.get_user(update.effective_user.id)
            uname = f"@{user['username']}" if user.get("username") else f"ID:{update.effective_user.id}"
            bonus_line = f" (+{req['bonus_percent']}% bonus)" if req["bonus_percent"] else ""
            caption = (
                f"🔔 Permintaan Top-up Baru\n\n"
                f"👤 User: {uname} (ID: {update.effective_user.id})\n"
                f"📦 Pakej: {pkg['name']} — RM {req['amount_rm']:.2f}{bonus_line}\n"
                f"🕐 {req['created_at'][:16]} UTC"
            )
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"admin:approve:{request_id}"),
                InlineKeyboardButton("❌ Reject",  callback_data=f"admin:reject:{request_id}"),
            ]])
            await context.bot.send_photo(
                chat_id=admin_chat_id,
                photo=file_id,
                caption=caption,
                reply_markup=markup,
            )
        except Exception:
            pass  # don't disrupt user if admin notification fails

    context.user_data.pop("topup_request_id", None)
    return ConversationHandler.END


# ── Cancel — used as ConversationHandler fallback AND global handler ───────────

async def cancel_topup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    request_id = query.data.split("topup:cancel:", 1)[1]
    db, *_ = get_services(context)
    try:
        req = await db.get_topup_request(request_id)
        if req["status"] in ("awaiting_receipt", "pending_review"):
            await db.update_topup_request(request_id, status="cancelled")
    except Exception:
        pass

    context.user_data.pop("topup_request_id", None)

    effective_user = update.effective_user
    if effective_user:
        try:
            text, markup = await build_menu_message(
                context, effective_user.id, effective_user.first_name
            )
            await query.edit_message_text(text, reply_markup=markup)
            return ConversationHandler.END
        except Exception:
            pass
    await query.edit_message_text("Dibatalkan.", reply_markup=back_to_menu_button())
    return ConversationHandler.END


# ── Admin: approve ─────────────────────────────────────────────────────────────

async def approve_topup_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    if not _is_admin(context, update.effective_user.id):
        await query.answer("Tiada kebenaran.", show_alert=True)
        return
    await query.answer()

    request_id = query.data.split("admin:approve:", 1)[1]
    db, *_ = get_services(context)

    try:
        user_id, new_balance, amount_rm, bonus_percent, pkg_name = await db.approve_topup(
            request_id, update.effective_user.id
        )
    except Exception as exc:
        await query.answer(f"Gagal: {exc}", show_alert=True)
        return

    admin_name = update.effective_user.first_name or str(update.effective_user.id)
    bonus_line = f" (+{bonus_percent}% bonus)" if bonus_percent else ""

    try:
        old_caption = query.message.caption or ""
        await query.edit_message_caption(
            caption=f"{old_caption}\n\n✅ Diluluskan oleh {admin_name}",
            reply_markup=None,
        )
    except Exception:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

    # Notify user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ Top-up berjaya!\n\n"
                f"📦 {pkg_name} — RM {amount_rm:.2f}{bonus_line}\n"
                f"Baki baru: RM {new_balance / 100:.2f}"
            ),
        )
    except Exception:
        pass


# ── Admin: reject ──────────────────────────────────────────────────────────────

async def reject_topup_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    if not _is_admin(context, update.effective_user.id):
        await query.answer("Tiada kebenaran.", show_alert=True)
        return
    await query.answer()

    request_id = query.data.split("admin:reject:", 1)[1]
    db, *_ = get_services(context)

    try:
        user_id, pkg_name = await db.reject_topup(request_id, update.effective_user.id)
    except Exception as exc:
        await query.answer(f"Gagal: {exc}", show_alert=True)
        return

    admin_name = update.effective_user.first_name or str(update.effective_user.id)

    try:
        old_caption = query.message.caption or ""
        await query.edit_message_caption(
            caption=f"{old_caption}\n\n❌ Ditolak oleh {admin_name}",
            reply_markup=None,
        )
    except Exception:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

    # Notify user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Pembayaran tidak dapat disahkan. Sila hubungi admin atau cuba semula.",
        )
    except Exception:
        pass


# ── ConversationHandler ────────────────────────────────────────────────────────

def build_topup_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(request_receipt, pattern=r"^topup:receipt:"),
        ],
        states={
            AWAIT_RECEIPT: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, receive_receipt),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_topup, pattern=r"^topup:cancel:"),
        ],
        allow_reentry=True,
        per_message=False,
    )
