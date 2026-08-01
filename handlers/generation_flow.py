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

# ── Conversation states ──────────────────────────────────────────────────────
CHOOSE_MODEL, CHOOSE_RATIO, AWAIT_IMAGE, AWAIT_PROMPT, CONFIRM = range(5)

# ── Helpers ──────────────────────────────────────────────────────────────────

def _ratio_icon(ratio: str) -> str:
    """Return an orientation icon based on the aspect ratio string."""
    try:
        w_str, h_str = ratio.split(":")
        w, h = int(w_str), int(h_str)
        if w > h:
            return "🖥️"   # landscape
        if h > w:
            return "📱"   # portrait
    except (ValueError, AttributeError):
        pass
    return "⬛"            # square / unknown


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
    rows.append([InlineKeyboardButton("◀️ Kembali", callback_data="gen:cancel")])
    return InlineKeyboardMarkup(rows)


def _ratio_keyboard(model: AIModel) -> InlineKeyboardMarkup:
    job_type = model.job_type
    rows = [
        [
            InlineKeyboardButton(
                f"{_ratio_icon(ratio)} {ratio}",
                callback_data=f"gen:{job_type}:ratio:{ratio}",
            )
        ]
        for ratio in model.supported_ratios
    ]
    rows.append([InlineKeyboardButton("◀️ Kembali", callback_data=f"gen:{job_type}:back_model")])
    return InlineKeyboardMarkup(rows)


def _info_card(model: AIModel) -> str:
    """Build the model info card text."""
    lines: list[str] = [
        f"🔥 {model.display_name}",
        "",
        model.description,
        "",
        f"⚠️ {model.display_name} di server ini menolak prompt lebih daripada "
        f"{model.max_prompt_chars} aksara.",
        "",
        "Yang anda hantar:",
        f"1. 📝 prompt (maks {model.max_prompt_chars} aksara)",
    ]
    if model.input_type in ("image_required", "image_optional"):
        label = "wajib" if model.input_type == "image_required" else "pilihan"
        lines.append(f"2. 📷 gambar ({label})")
    lines += [
        "",
        f"Kualiti: {model.resolution} · "
        f"{'audio tersedia' if model.has_audio else 'tiada audio'}",
    ]
    if model.duration_seconds:
        lines.append(f"🕐 {model.duration_seconds}s")
    if model.prompt_tips:
        lines += ["", "💡 Tips prompt:"]
        for tip in model.prompt_tips:
            lines.append(f"• {tip}")
    lines += ["", "📐 Pilih rasio (aspect ratio):"]
    return "\n".join(lines)


# ── Entry ────────────────────────────────────────────────────────────────────

async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    job_type = context.user_data["job_type"]
    if not update.message:
        return ConversationHandler.END
    await update.message.reply_text(
        f"Pilih model untuk {'video' if job_type == 'video' else 'gambar'}:",
        reply_markup=_model_keyboard(job_type),
    )
    return CHOOSE_MODEL


# ── Step 1 → 2: choose model, show info card + ratio keyboard ────────────────

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
    await query.edit_message_text(
        _info_card(model),
        reply_markup=_ratio_keyboard(model),
    )
    return CHOOSE_RATIO


# ── Back from CHOOSE_RATIO → re-show model list ──────────────────────────────

async def back_to_model_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    job_type = context.user_data.get("job_type", "video")
    context.user_data.pop("model_key", None)
    await query.edit_message_text(
        f"Pilih model untuk {'video' if job_type == 'video' else 'gambar'}:",
        reply_markup=_model_keyboard(job_type),
    )
    return CHOOSE_MODEL


# ── Step 2 → 3: choose ratio ─────────────────────────────────────────────────

async def choose_ratio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    # callback_data format: gen:{job_type}:ratio:{ratio_label}
    ratio = query.data.split("ratio:", 1)[-1]
    context.user_data["selected_ratio"] = ratio
    model = MODEL_BY_KEY[context.user_data["model_key"]]
    if model.input_type in ("image_required", "image_optional"):
        optional = model.input_type == "image_optional"
        skip_hint = "\n\nHantar /skip jika mahu guna teks sahaja." if optional else ""
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Kembali", callback_data=f"gen:{model.job_type}:back_model")]
        ])
        await query.edit_message_text(
            f"Rasio dipilih: {ratio}\n\n"
            f"Sila hantar gambar JPG/PNG (maksimum 10MB).{skip_hint}",
            reply_markup=back_kb,
        )
        return AWAIT_IMAGE
    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Kembali", callback_data=f"gen:{model.job_type}:back_model")]
    ])
    await query.edit_message_text(
        f"Rasio dipilih: {ratio}\n\n"
        f"Terangkan {'video' if model.job_type == 'video' else 'gambar'} yang anda mahu "
        f"(maks {model.max_prompt_chars} aksara).",
        reply_markup=back_kb,
    )
    return AWAIT_PROMPT


# ── Back from AWAIT_IMAGE → re-show info card + ratio keyboard ────────────────

async def back_to_ratio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    model_key = context.user_data.get("model_key")
    model = MODEL_BY_KEY.get(model_key or "")
    if not model:
        return ConversationHandler.END
    context.user_data.pop("selected_ratio", None)
    context.user_data.pop("image_path", None)
    await query.edit_message_text(
        _info_card(model),
        reply_markup=_ratio_keyboard(model),
    )
    return CHOOSE_RATIO


# ── Step 3 (optional): receive / skip image ───────────────────────────────────

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
    model = MODEL_BY_KEY[context.user_data["model_key"]]
    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Kembali", callback_data=f"gen:{model.job_type}:back_ratio")]
    ])
    await update.message.reply_text(
        f"Gambar diterima. Terangkan {'video' if model.job_type == 'video' else 'gambar'} "
        f"yang anda mahu (maks {model.max_prompt_chars} aksara).",
        reply_markup=back_kb,
    )
    return AWAIT_PROMPT


async def skip_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    model = MODEL_BY_KEY[context.user_data["model_key"]]
    if model.input_type != "image_optional":
        await update.message.reply_text("Model ini memerlukan gambar.")
        return AWAIT_IMAGE
    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Kembali", callback_data=f"gen:{model.job_type}:back_ratio")]
    ])
    await update.message.reply_text(
        f"Baik, kita guna teks sahaja. Terangkan "
        f"{'video' if model.job_type == 'video' else 'gambar'} "
        f"yang anda mahu (maks {model.max_prompt_chars} aksara).",
        reply_markup=back_kb,
    )
    return AWAIT_PROMPT


# ── Back from AWAIT_PROMPT → re-show image request or ratio selection ─────────

async def back_from_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    model_key = context.user_data.get("model_key")
    model = MODEL_BY_KEY.get(model_key or "")
    if not model:
        return ConversationHandler.END
    context.user_data.pop("prompt", None)
    # If model needs an image, go back to the image request step
    if model.input_type in ("image_required", "image_optional"):
        # Clean up any previously uploaded image
        if img := context.user_data.pop("image_path", None):
            try:
                os.unlink(img)
            except OSError:
                pass
        optional = model.input_type == "image_optional"
        skip_hint = "\n\nHantar /skip jika mahu guna teks sahaja." if optional else ""
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Kembali", callback_data=f"gen:{model.job_type}:back_model")]
        ])
        await query.edit_message_text(
            f"Sila hantar gambar JPG/PNG (maksimum 10MB).{skip_hint}",
            reply_markup=back_kb,
        )
        return AWAIT_IMAGE
    # text_only: go back to ratio selection
    context.user_data.pop("selected_ratio", None)
    await query.edit_message_text(
        _info_card(model),
        reply_markup=_ratio_keyboard(model),
    )
    return CHOOSE_RATIO


# ── Step 4: receive prompt ────────────────────────────────────────────────────

async def receive_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return AWAIT_PROMPT
    prompt = update.message.text.strip()
    model = MODEL_BY_KEY[context.user_data["model_key"]]
    if len(prompt) < 3:
        await update.message.reply_text("Prompt terlalu pendek. Sila terangkan dengan lebih jelas.")
        return AWAIT_PROMPT
    if len(prompt) > model.max_prompt_chars:
        await update.message.reply_text(
            f"Prompt terlalu panjang ({len(prompt)} aksara). "
            f"Had maksimum untuk model ini ialah {model.max_prompt_chars} aksara."
        )
        return AWAIT_PROMPT
    db, *_ = get_services(context)
    balance = await db.balance(update.effective_user.id)
    context.user_data["prompt"] = prompt
    if balance < model.sell_price_sen:
        await update.message.reply_text(
            f"Baki tidak mencukupi. Kos: {money(model.sell_price_sen)}; "
            f"baki: {money(balance)}.\nGunakan menu Kredit untuk top-up."
        )
        return ConversationHandler.END
    selected_ratio = context.user_data.get("selected_ratio", "")
    ratio_info = f"\nRasio: {selected_ratio}" if selected_ratio else ""
    await update.message.reply_text(
        f"Ringkasan permintaan:\n\n"
        f"Model: {model.display_name}\n"
        f"Spesifikasi: {model.spec_label}"
        f"{ratio_info}\n"
        f"Kos: {money(model.sell_price_sen)}\n"
        f"Prompt: {prompt}\n\n"
        "Teruskan?",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Confirm", callback_data="gen:confirm"),
                    InlineKeyboardButton("❌ Cancel", callback_data="gen:cancel"),
                ]
            ]
        ),
    )
    return CONFIRM


# ── Step 5: confirm & submit ──────────────────────────────────────────────────

async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not update.effective_user:
        return ConversationHandler.END
    await query.answer()
    model = MODEL_BY_KEY[context.user_data["model_key"]]
    db, generation, *_ = get_services(context)
    user_id = update.effective_user.id
    image_path = Path(context.user_data["image_path"]) if context.user_data.get("image_path") else None

    # Build extra fal.ai arguments from the selected aspect ratio
    selected_ratio = context.user_data.get("selected_ratio", "")
    extra_args: dict = model.ratio_to_dimension_map.get(selected_ratio, {})

    try:
        job = await generation.start(
            user_id,
            model,
            context.user_data["prompt"],
            image_path,
            _delivery(context, user_id, model.job_type),
            extra_args=extra_args or None,
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
        for key in ("image_path", "prompt", "model_key", "selected_ratio"):
            context.user_data.pop(key, None)

    settings = context.application.bot_data["settings"]
    await db.settle_referral(user_id, settings.referral_bonus)
    await query.edit_message_text(
        f"Sedang diproses...\nJob ID: {job['id']}\n\n"
        "Anda boleh terus guna bot. Saya akan hantar hasil di sini bila siap."
    )
    return ConversationHandler.END


# ── Delivery callback ─────────────────────────────────────────────────────────

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


# ── Cancel (global fallback) ──────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Permintaan dibatalkan.")
    elif update.message:
        await update.message.reply_text("Permintaan dibatalkan.", reply_markup=main_keyboard())
    # Clean up any temp image
    if img := context.user_data.pop("image_path", None):
        try:
            os.unlink(img)
        except OSError:
            pass
    context.user_data.clear()
    return ConversationHandler.END


# ── Conversation builder ──────────────────────────────────────────────────────

def build_generation_conversation(job_type: str) -> ConversationHandler:
    jt = job_type  # short alias for callback patterns

    return ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex(f"^Buat {'Video' if jt == 'video' else 'Gambar'}$"),
                _entry(jt),
            ),
        ],
        states={
            CHOOSE_MODEL: [
                CallbackQueryHandler(choose_model, pattern=fr"^gen:{jt}:model:"),
            ],
            CHOOSE_RATIO: [
                CallbackQueryHandler(choose_ratio,       pattern=fr"^gen:{jt}:ratio:"),
                CallbackQueryHandler(back_to_model_list, pattern=fr"^gen:{jt}:back_model$"),
            ],
            AWAIT_IMAGE: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, receive_image),
                CommandHandler("skip", skip_image),
                CallbackQueryHandler(back_to_ratio,      pattern=fr"^gen:{jt}:back_model$"),
            ],
            AWAIT_PROMPT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prompt),
                CallbackQueryHandler(back_from_prompt,   pattern=fr"^gen:{jt}:back_ratio$"),
                CallbackQueryHandler(back_from_prompt,   pattern=fr"^gen:{jt}:back_model$"),
            ],
            CONFIRM: [
                CallbackQueryHandler(confirm, pattern=r"^gen:confirm$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern=r"^gen:cancel$"),
            CommandHandler("cancel", cancel),
        ],
        allow_reentry=True,
        per_message=False,
    )


def _entry(job_type: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["job_type"] = job_type
        return await begin(update, context)

    return handler
