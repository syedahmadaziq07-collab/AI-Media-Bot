"""Generation conversation handler — video and image flows share this module.

State machine:
  CHOOSE_MODEL → CHOOSE_RATIO → AWAIT_INPUT → CONFIRM → (submit job)

ONE bot message is used throughout the whole flow and edited in-place via
query.edit_message_text() (for inline-button callbacks) or context.bot.edit_message_text()
(for message-triggered handlers that receive a user photo/text).  begin() sends the
initial message and stores its ID as conv_msg_id so all subsequent steps can edit it.

AWAIT_INPUT is a single state that accepts either a PHOTO or TEXT message:
  • PHOTO  — saves image to temp file, stays in AWAIT_INPUT waiting for a prompt
  • TEXT   — validates length, saves prompt, transitions to CONFIRM
  • Another PHOTO before prompt is sent — replaces the previous image silently
  • Callback ◀️ Kembali — goes back to CHOOSE_RATIO (info card + ratio keyboard)

CONFIRM shows a formatted summary with three buttons:
  ✅ Generate — debit credit and submit to fal.ai
  ✏️ Ubah    — back to AWAIT_INPUT keeping model + ratio (clears prompt + image)
  ❌ Batal   — cancel and return to main menu without any charge
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from models_config import AIModel, MODEL_BY_KEY, models_for
from .common import back_to_menu_button, build_menu_message, get_services, main_menu_markup

# ── Conversation states ──────────────────────────────────────────────────────
CHOOSE_MODEL, CHOOSE_RATIO, AWAIT_INPUT, CONFIRM = range(4)

# ── Price helpers ────────────────────────────────────────────────────────────

def _fmt_price(sell_price_sen: int) -> str:
    """Return 'RM X.XX' from sen value."""
    return f"RM {sell_price_sen / 100:.2f}"


def _job_emoji(job_type: str) -> str:
    return "🎬" if job_type == "video" else "🖼️"


# ── Ratio icon ────────────────────────────────────────────────────────────────

def _ratio_icon(ratio: str) -> str:
    try:
        w, h = (int(x) for x in ratio.split(":"))
        if w > h:
            return "🖥️"
        if h > w:
            return "📱"
    except (ValueError, AttributeError):
        pass
    return "⬛"


# ── Keyboard builders ─────────────────────────────────────────────────────────

def _model_keyboard(job_type: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"{model.display_name} · RM {model.sell_price_sen / 100:.2f}",
                callback_data=f"gen:{job_type}:model:{model.key}",
            )
        ]
        for model in models_for(job_type)
    ]
    rows.append([InlineKeyboardButton("◀️ Kembali", callback_data="gen:cancel")])
    return InlineKeyboardMarkup(rows)


def _ratio_keyboard(model: AIModel) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"{_ratio_icon(r)} {r}",
                callback_data=f"gen:{model.job_type}:ratio:{r}",
            )
        ]
        for r in model.supported_ratios
    ]
    rows.append(
        [InlineKeyboardButton("◀️ Kembali", callback_data=f"gen:{model.job_type}:back_model")]
    )
    return InlineKeyboardMarkup(rows)


def _info_card(model: AIModel) -> str:
    """Multi-line info card shown when user picks a model (before ratio selection)."""
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


def _input_prompt_text(model: AIModel, ratio: str) -> str:
    """Combined single-message shown after user picks a ratio."""
    duration_str = f"{model.duration_seconds}s" if model.duration_seconds else ""
    header = f"{_job_emoji(model.job_type)} {model.display_name}"
    if duration_str:
        header += f" ({duration_str})"
    header += f" ({ratio})"

    subtitle_parts = [p for p in [model.description, duration_str, model.resolution] if p]
    subtitle_parts.append("audio tersedia" if model.has_audio else "audio tiada")
    subtitle = " · ".join(subtitle_parts)

    lines = [header, f"<i>{subtitle}</i>", ""]

    if model.input_type in ("image_required", "image_optional"):
        lines.append(
            "📷 Anda juga boleh hantar gambar rujukan dulu (pilihan), "
            "kemudian tulis prompt anda."
        )
        lines.append("")

    lines.append(
        f"✍️ Tulis prompt anda sekarang (maks {model.max_prompt_chars} aksara)."
    )
    return "\n".join(lines)


def _input_back_keyboard(job_type: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("◀️ Kembali", callback_data=f"gen:{job_type}:back_ratio")]]
    )


def _confirm_text(model: AIModel, ratio: str, prompt: str, has_image: bool) -> str:
    duration_str = f"{model.duration_seconds}s" if model.duration_seconds else "—"
    image_line = "\n📷 Gambar rujukan: ✅ disertakan" if has_image else ""
    return (
        "📋 <b>Sedia generate?</b>\n\n"
        f"{_job_emoji(model.job_type)} {model.display_name}\n"
        f"🕐 {duration_str}   🖥️ {model.resolution}   📐 {ratio}"
        f"{image_line}\n\n"
        f'📝 "<i>{prompt}</i>"\n\n'
        f"💰 Ini akan guna {_fmt_price(model.sell_price_sen)}."
    )


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Generate", callback_data="gen:confirm")],
            [InlineKeyboardButton("✏️ Ubah", callback_data="gen:edit")],
            [InlineKeyboardButton("❌ Batal", callback_data="gen:cancel")],
        ]
    )


# ── Helpers for cleanup & in-place editing ───────────────────────────────────

def _clear_image(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove any stored temp image file and clear user_data."""
    if img := context.user_data.pop("image_path", None):
        try:
            os.unlink(img)
        except OSError:
            pass


def _store_conv_msg(context: ContextTypes.DEFAULT_TYPE, msg) -> None:
    """Remember the bot's conversation message so message handlers can edit it."""
    context.user_data["conv_msg_id"] = msg.message_id
    context.user_data["conv_chat_id"] = msg.chat_id


async def _edit_conv_msg(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup=None,
    parse_mode: str | None = None,
) -> None:
    """Edit the stored conversation message in-place (used by message handlers)."""
    msg_id = context.user_data.get("conv_msg_id")
    chat_id = context.user_data.get("conv_chat_id")
    if not msg_id or not chat_id:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except Exception:
        pass  # message may have been deleted; silently ignore


# ── Entry ─────────────────────────────────────────────────────────────────────

async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    job_type = context.user_data["job_type"]
    text = f"Pilih model untuk {'video' if job_type == 'video' else 'gambar'}:"
    markup = _model_keyboard(job_type)
    if update.callback_query:
        msg = await update.callback_query.edit_message_text(text, reply_markup=markup)
        _store_conv_msg(context, msg)
    elif update.message:
        msg = await update.message.reply_text(text, reply_markup=markup)
        _store_conv_msg(context, msg)
    else:
        return ConversationHandler.END
    return CHOOSE_MODEL


# ── CHOOSE_MODEL → CHOOSE_RATIO ───────────────────────────────────────────────

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
    await query.edit_message_text(_info_card(model), reply_markup=_ratio_keyboard(model))
    return CHOOSE_RATIO


# ── Back: CHOOSE_RATIO → CHOOSE_MODEL ────────────────────────────────────────

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


# ── CHOOSE_RATIO → AWAIT_INPUT ────────────────────────────────────────────────

async def choose_ratio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    ratio = query.data.split("ratio:", 1)[-1]
    context.user_data["selected_ratio"] = ratio
    # Clear any leftover input from a previous attempt
    _clear_image(context)
    context.user_data.pop("prompt", None)
    model = MODEL_BY_KEY[context.user_data["model_key"]]
    await query.edit_message_text(
        _input_prompt_text(model, ratio),
        reply_markup=_input_back_keyboard(model.job_type),
        parse_mode=ParseMode.HTML,
    )
    return AWAIT_INPUT


# ── Back: AWAIT_INPUT → CHOOSE_RATIO (re-show info card + ratio keyboard) ─────

async def back_to_ratio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    _clear_image(context)
    context.user_data.pop("prompt", None)
    context.user_data.pop("selected_ratio", None)
    model_key = context.user_data.get("model_key")
    model = MODEL_BY_KEY.get(model_key or "")
    if not model:
        return ConversationHandler.END
    await query.edit_message_text(_info_card(model), reply_markup=_ratio_keyboard(model))
    return CHOOSE_RATIO


# ── AWAIT_INPUT: photo ────────────────────────────────────────────────────────

async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return AWAIT_INPUT
    model = MODEL_BY_KEY[context.user_data["model_key"]]
    back_kb = _input_back_keyboard(model.job_type)

    if model.input_type == "text_only":
        await _edit_conv_msg(
            context,
            "⚠️ Model ini hanya terima teks. Sila tulis prompt anda.",
            reply_markup=back_kb,
        )
        return AWAIT_INPUT

    image = update.message.photo[-1] if update.message.photo else update.message.document
    if not image:
        return AWAIT_INPUT
    file_size = getattr(image, "file_size", 0) or 0
    if file_size > 10 * 1024 * 1024:
        await _edit_conv_msg(
            context,
            "⚠️ Fail terlalu besar. Had maksimum ialah 10MB. Sila hantar gambar yang lebih kecil.",
            reply_markup=back_kb,
        )
        return AWAIT_INPUT
    if update.message.document:
        mime = update.message.document.mime_type or ""
        if mime not in ("image/jpeg", "image/png"):
            await _edit_conv_msg(
                context,
                "⚠️ Format tidak disokong. Sila hantar gambar dalam format JPG atau PNG.",
                reply_markup=back_kb,
            )
            return AWAIT_INPUT

    # Replace any previously stored image
    _clear_image(context)

    tg_file = await image.get_file()
    temp = tempfile.NamedTemporaryFile(prefix="jagovideo_", suffix=".jpg", delete=False)
    temp.close()
    await tg_file.download_to_drive(temp.name)
    context.user_data["image_path"] = temp.name

    tip_line = f"\n\n💡 Tips: {model.prompt_tips[0]}" if model.prompt_tips else ""
    await _edit_conv_msg(
        context,
        f"✅ Gambar diterima. Sila tulis prompt anda sekarang.{tip_line}",
        reply_markup=back_kb,
    )
    return AWAIT_INPUT


# ── AWAIT_INPUT: text → CONFIRM ───────────────────────────────────────────────

async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return AWAIT_INPUT
    model = MODEL_BY_KEY[context.user_data["model_key"]]
    back_kb = _input_back_keyboard(model.job_type)
    prompt = update.message.text.strip()
    if len(prompt) < 3:
        await _edit_conv_msg(
            context,
            "⚠️ Prompt terlalu pendek. Sila terangkan dengan lebih jelas.",
            reply_markup=back_kb,
        )
        return AWAIT_INPUT
    if len(prompt) > model.max_prompt_chars:
        await _edit_conv_msg(
            context,
            f"⚠️ Prompt terlalu panjang ({len(prompt)} aksara). "
            f"Had maksimum untuk model ini ialah {model.max_prompt_chars} aksara.",
            reply_markup=back_kb,
        )
        return AWAIT_INPUT

    db, *_ = get_services(context)
    balance = await db.balance(update.effective_user.id)
    if balance < model.sell_price_sen:
        await _edit_conv_msg(
            context,
            f"❌ Baki tidak mencukupi.\n"
            f"Kos: {_fmt_price(model.sell_price_sen)}\n"
            f"Baki semasa: {_fmt_price(balance)}\n\n"
            "Gunakan menu Kredit untuk top-up.",
            reply_markup=back_to_menu_button(),
        )
        _clear_image(context)
        context.user_data.clear()
        return ConversationHandler.END

    context.user_data["prompt"] = prompt
    ratio = context.user_data.get("selected_ratio", "")
    has_image = bool(context.user_data.get("image_path"))
    await _edit_conv_msg(
        context,
        _confirm_text(model, ratio, prompt, has_image),
        reply_markup=_confirm_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    return CONFIRM


# ── CONFIRM: ✅ Generate ──────────────────────────────────────────────────────

async def confirm_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not update.effective_user:
        return ConversationHandler.END
    await query.answer()

    model = MODEL_BY_KEY[context.user_data["model_key"]]
    db, generation, *_ = get_services(context)
    user_id = update.effective_user.id
    image_path = Path(p) if (p := context.user_data.get("image_path")) else None
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
        await query.edit_message_text(
            "Baki berubah semasa permintaan. Kredit tidak mencukupi.",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END
    except Exception:
        await query.edit_message_text(
            "Permintaan gagal dihantar. Kredit telah dipulangkan jika telah ditolak.",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END
    finally:
        if image_path:
            try:
                os.unlink(image_path)
            except OSError:
                pass
        for key in ("image_path", "prompt", "model_key", "selected_ratio",
                    "conv_msg_id", "conv_chat_id", "job_type"):
            context.user_data.pop(key, None)

    settings = context.application.bot_data["settings"]
    await db.settle_referral(user_id, settings.referral_bonus)
    await query.edit_message_text(
        f"⏳ Sedang diproses...\n"
        f"Job ID: <code>{job['id']}</code>\n\n"
        "Anda boleh terus guna bot. Saya akan hantar hasil di sini bila siap.",
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


# ── CONFIRM: ✏️ Ubah — back to AWAIT_INPUT keeping model + ratio ───────────

async def confirm_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    # Clear only prompt + image; keep model_key and selected_ratio
    _clear_image(context)
    context.user_data.pop("prompt", None)
    model = MODEL_BY_KEY[context.user_data["model_key"]]
    ratio = context.user_data.get("selected_ratio", "")
    await query.edit_message_text(
        _input_prompt_text(model, ratio),
        reply_markup=_input_back_keyboard(model.job_type),
        parse_mode=ParseMode.HTML,
    )
    return AWAIT_INPUT


# ── Delivery callback ─────────────────────────────────────────────────────────

def _delivery(context: ContextTypes.DEFAULT_TYPE, user_id: int, job_type: str):
    async def deliver(job: dict) -> None:
        if job["status"] == "completed" and job.get("output_url"):
            if job_type == "video":
                await context.bot.send_video(
                    chat_id=user_id,
                    video=job["output_url"],
                    caption=f"✅ Siap!\nJob ID: {job['id']}",
                )
            else:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=job["output_url"],
                    caption=f"✅ Siap!\nJob ID: {job['id']}",
                )
        elif job["status"] == "failed":
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ Generasi gagal untuk job {job['id']}. Kredit telah dipulangkan.",
            )

    return deliver


# ── Cancel / global fallback ──────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_image(context)
    effective_user = update.effective_user
    if effective_user:
        try:
            text, markup = await build_menu_message(
                context, effective_user.id, effective_user.first_name
            )
        except Exception:
            text = "Permintaan dibatalkan. Guna /start untuk kembali ke menu."
            markup = main_menu_markup()
    else:
        text = "Permintaan dibatalkan."
        markup = None
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    elif update.message:
        # /cancel command — edit the stored conv message back to main menu
        await _edit_conv_msg(context, text, reply_markup=markup)
    for key in ("conv_msg_id", "conv_chat_id", "image_path", "prompt",
                "model_key", "selected_ratio", "job_type"):
        context.user_data.pop(key, None)
    return ConversationHandler.END


# ── Conversation builder ──────────────────────────────────────────────────────

def build_generation_conversation(job_type: str) -> ConversationHandler:
    jt = job_type

    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(_entry(jt), pattern=fr"^menu:{jt}$"),
        ],
        states={
            CHOOSE_MODEL: [
                CallbackQueryHandler(choose_model, pattern=fr"^gen:{jt}:model:"),
            ],
            CHOOSE_RATIO: [
                CallbackQueryHandler(choose_ratio,       pattern=fr"^gen:{jt}:ratio:"),
                CallbackQueryHandler(back_to_model_list, pattern=fr"^gen:{jt}:back_model$"),
            ],
            AWAIT_INPUT: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, receive_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text),
                CallbackQueryHandler(back_to_ratio, pattern=fr"^gen:{jt}:back_ratio$"),
            ],
            CONFIRM: [
                CallbackQueryHandler(confirm_generate, pattern=r"^gen:confirm$"),
                CallbackQueryHandler(confirm_edit,     pattern=r"^gen:edit$"),
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
        if update.callback_query:
            await update.callback_query.answer()
        context.user_data["job_type"] = job_type
        return await begin(update, context)

    return handler
