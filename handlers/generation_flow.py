from __future__ import annotations

import os
import tempfile
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from models_config import AIModel, MODEL_BY_KEY, models_for
from .common import get_services, main_keyboard, money

CHOOSE_MODEL, AWAIT_IMAGE, AWAIT_PROMPT, CONFIRM = range(4)


def _model_keyboard(job_type: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"{model.display_name} · {model.price_label}",
                callback_data=f"gen:{job_type}:model:{model.key}",
            )
        ]
        for model in models_for(job_type)
    ]
    rows.append([InlineKeyboardButton("Kembali", callback_data="gen:cancel")])
    return InlineKeyboardMarkup(rows)


async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    job_type = context.user_data["job_type"]
    if not update.message:
        return ConversationHandler.END
    await update.message.reply_text(
        f"Pilih model untuk {'video' if job_type == 'video' else 'gambar'}:",
        reply_markup=_model_keyboard(job_type),
    )
    return CHOOSE_MODEL


async def choose_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    key = query.data.rsplit(":", 1)[-1]
    model = MODEL_BY_KEY.get(key)
    if not model:
        await query.edit_message_text("Model tidak ditemui. Sila cuba semula.")
        return ConversationHandler.END
    context.user_data["model_key"] = model.key
    if model.input_type in ("image_required", "image_optional"):
        optional = model.input_type == "image_optional"
        skip = "\nHantar /skip jika mahu guna teks sahaja." if optional else ""
        await query.edit_message_text(
            f"Model dipilih: {model.display_name}\n"
            f"Sila hantar gambar JPG/PNG (maksimum 10MB).{skip}"
        )
        return AWAIT_IMAGE
    await query.edit_message_text(
        f"Model dipilih: {model.display_name}\n\nTerangkan video/gambar yang anda mahu."
    )
    return AWAIT_PROMPT


async def receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return AWAIT_IMAGE
    image = update.message.photo[-1] if update.message.photo else update.message.document
    if not image:
        return AWAIT_IMAGE
    file_size = getattr(image, "file_size", 0) or 0
    if file_size > 10 * 1024 * 1024:
        await update.message.reply_text("Fail terlalu besar. Had maksimum ialah 10MB.")
        return AWAIT_IMAGE
    if update.message.document:
        mime = update.message.document.mime_type or ""
        if mime not in ("image/jpeg", "image/png"):
            await update.message.reply_text("Format disokong hanya JPG atau PNG.")
            return AWAIT_IMAGE
    tg_file = await image.get_file()
    temp = tempfile.NamedTemporaryFile(prefix="jagovideo_", suffix=".jpg", delete=False)
    temp.close()
    await tg_file.download_to_drive(temp.name)
    context.user_data["image_path"] = temp.name
    await update.message.reply_text("Gambar diterima. Sekarang terangkan video/gambar yang anda mahu.")
    return AWAIT_PROMPT


async def skip_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    model = MODEL_BY_KEY[context.user_data["model_key"]]
    if model.input_type != "image_optional":
        await update.message.reply_text("Model ini memerlukan gambar.")
        return AWAIT_IMAGE
    await update.message.reply_text("Baik, kita guna teks sahaja. Terangkan hasil yang anda mahu.")
    return AWAIT_PROMPT


async def receive_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return AWAIT_PROMPT
    prompt = update.message.text.strip()
    if len(prompt) < 3:
        await update.message.reply_text("Prompt terlalu pendek. Sila terangkan dengan lebih jelas.")
        return AWAIT_PROMPT
    model = MODEL_BY_KEY[context.user_data["model_key"]]
    db, *_ = get_services(context)
    balance = await db.balance(update.effective_user.id)
    context.user_data["prompt"] = prompt
    if balance < model.sell_price_sen:
        await update.message.reply_text(
            f"Baki tidak mencukupi. Kos: {money(model.sell_price_sen)}; "
            f"baki: {money(balance)}.\nGunakan menu Kredit untuk top-up."
        )
        return ConversationHandler.END
    context.user_data["model"] = model.key
    await update.message.reply_text(
        f"Ringkasan permintaan:\n\n"
        f"Model: {model.display_name}\n"
        f"Spesifikasi: {model.spec_label}\n"
        f"Kos: {money(model.sell_price_sen)}\n"
        f"Prompt: {prompt}\n\n"
        "Teruskan?",
        reply_markup=InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("Confirm", callback_data="gen:confirm"),
                InlineKeyboardButton("Cancel", callback_data="gen:cancel"),
            ]]
        ),
    )
    return CONFIRM


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not update.effective_user:
        return ConversationHandler.END
    await query.answer()
    model = MODEL_BY_KEY[context.user_data["model"]]
    db, generation, *_ = get_services(context)
    user_id = update.effective_user.id
    image_path = Path(context.user_data["image_path"]) if context.user_data.get("image_path") else None
    try:
        job = await generation.start(
            user_id,
            model,
            context.user_data["prompt"],
            image_path,
            _delivery(context, user_id, model.job_type),
        )
    except ValueError:
        await query.edit_message_text("Baki berubah semasa permintaan. Kredit tidak mencukupi.")
        return ConversationHandler.END
    except Exception:
        await query.edit_message_text("Permintaan gagal dihantar. Kredit telah dipulangkan jika telah ditolak.")
        return ConversationHandler.END
    finally:
        if image_path:
            try:
                os.unlink(image_path)
            except OSError:
                pass
        for key in ("image_path", "prompt", "model", "model_key"):
            context.user_data.pop(key, None)
    settings = context.application.bot_data["settings"]
    await db.settle_referral(user_id, settings.referral_bonus)
    await query.edit_message_text(
        f"Sedang diproses...\nJob ID: {job['id']}\n\n"
        "Anda boleh terus guna bot. Saya akan hantar hasil di sini bila siap."
    )
    return ConversationHandler.END


def _delivery(context: ContextTypes.DEFAULT_TYPE, user_id: int, job_type: str):
    async def deliver(job: dict) -> None:
        if job["status"] == "completed" and job.get("output_url"):
            if job_type == "video":
                await context.bot.send_video(
                    chat_id=user_id,
                    video=job["output_url"],
                    caption=f"Siap.\nJob ID: {job['id']}",
                )
            else:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=job["output_url"],
                    caption=f"Siap.\nJob ID: {job['id']}",
                )
        elif job["status"] == "failed":
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Generasi gagal untuk job {job['id']}. Kredit telah dipulangkan.",
            )

    return deliver


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Permintaan dibatalkan.")
    elif update.message:
        await update.message.reply_text("Permintaan dibatalkan.", reply_markup=main_keyboard())
    context.user_data.clear()
    return ConversationHandler.END


def build_generation_conversation(job_type: str) -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(f"^Buat {'Video' if job_type == 'video' else 'Gambar'}$"), _entry(job_type)),
        ],
        states={
            CHOOSE_MODEL: [CallbackQueryHandler(choose_model, pattern=fr"^gen:{job_type}:model:")],
            AWAIT_IMAGE: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, receive_image),
                CommandHandler("skip", skip_image),
            ],
            AWAIT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prompt)],
            CONFIRM: [CallbackQueryHandler(confirm, pattern=r"^gen:confirm$")],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern=r"^gen:cancel$"),
            CommandHandler("cancel", cancel),
        ],
        allow_reentry=True,
    )


def _entry(job_type: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["job_type"] = job_type
        return await begin(update, context)

    return handler