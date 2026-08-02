"""Stateless handler functions for all bot flows.

Every handler receives a raw `telegram.Bot` instance and the relevant Telegram
object (Message or CallbackQuery).  State that would normally live in
ConversationHandler.user_data is persisted in the `conversation_state` table via
db.queries so that each Vercel invocation starts from a clean Python process.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import traceback
from datetime import UTC, datetime, timedelta
from uuid import uuid4

# Short alias — wraps every synchronous Supabase call so it runs in a thread
# pool instead of blocking the asyncio event loop.
_db = asyncio.to_thread

from telegram import Bot, CallbackQuery, Message
from telegram.constants import ParseMode

import db.queries as q
import services.credit_service as credit
import services.fal_service as fal
from bot.keyboards import (
    admin_review_markup,
    await_input_markup,
    back_to_menu_markup,
    confirm_markup,
    history_markup,
    main_menu_markup,
    model_list_markup,
    money,
    packages_markup,
    ratio_markup,
    topup_action_markup,
)
from bot.states import AWAIT_INPUT, AWAIT_RECEIPT, CHOOSE_RATIO, CONFIRM
from models_config import MODEL_BY_KEY, MODELS, models_for

logger = logging.getLogger(__name__)

# ── Config helpers ─────────────────────────────────────────────────────────────

def _bot_name() -> str:
    return os.environ.get("BOT_NAME", "JagoVideo Clone")


def _checkin_bonus() -> int:
    return int(os.environ.get("CHECKIN_BONUS", "50"))


def _referral_bonus() -> int:
    return int(os.environ.get("REFERRAL_BONUS", "100"))


def _admin_ids() -> set[int]:
    raw = os.environ.get("ADMIN_USER_IDS", "")
    ids: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if item:
            try:
                ids.add(int(item))
            except ValueError:
                pass
    return ids


def _admin_chat_id() -> int | None:
    raw = os.environ.get("ADMIN_CHAT_ID", "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _vercel_domain() -> str:
    return os.environ.get("VERCEL_DOMAIN", "").rstrip("/")


def _is_admin(user_id: int) -> bool:
    return user_id in _admin_ids()


# ── Menu ───────────────────────────────────────────────────────────────────────

async def show_main_menu(bot: Bot, chat_id: int, user_id: int, first_name: str, message_id: int | None = None) -> None:
    # Run independent DB calls in parallel — halves the round-trip count here.
    user, stats = await asyncio.gather(
        asyncio.to_thread(q.get_user, user_id),
        asyncio.to_thread(q.user_stats, user_id),
    )
    groups: dict[str, list[str]] = {}
    for model in MODELS:
        groups.setdefault(model.server_group, []).append(model.display_name)
    model_text = "\n".join(f"• {g}: {', '.join(ns)}" for g, ns in groups.items())
    text = (
        f"Selamat datang ke {_bot_name()}, {first_name}.\n\n"
        f"Baki kredit: {money(int(user['balance']))}\n"
        f"Generasi: {stats['completed']} siap / {stats['total']} jumlah\n\n"
        f"Model tersedia:\n{model_text}\n\n"
        "Pilih apa yang anda mahu buat:"
    )
    markup = main_menu_markup()
    if message_id:
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    print(f"[DEBUG] Calling send_message to chat_id={chat_id} with text length={len(text)}", flush=True)
    try:
        await bot.send_message(chat_id, text, reply_markup=markup)
        print("[DEBUG] send_message returned successfully", flush=True)
    except Exception as e:
        print(f"[ERROR] send_message failed: type={type(e).__name__} message={e}", flush=True)
        print(traceback.format_exc(), flush=True)
        raise


# ── /start command ─────────────────────────────────────────────────────────────

async def handle_start(message: Message, bot: Bot) -> None:
    user = message.from_user
    if not user:
        return

    print(f"[DEBUG] /start received, user_id={user.id}", flush=True)
    _t0 = time.time()

    try:
        # Parse referral arg
        referred_by: int | None = None
        args = (message.text or "").split()
        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                referred_by = int(args[1][4:])
            except ValueError:
                pass

        # upsert_user now uses a single Supabase upsert (was SELECT + INSERT/UPDATE).
        await asyncio.to_thread(
            q.upsert_user, user.id, user.username, user.first_name or str(user.id), referred_by
        )

        print(
            f"[DEBUG] Total processing time before send_message: {time.time() - _t0:.2f}s",
            flush=True,
        )
        await show_main_menu(bot, message.chat_id, user.id, user.first_name or str(user.id))
        print("[DEBUG] Welcome message sent successfully", flush=True)

        # clear_conversation_state moved after send_message — user gets reply faster.
        await asyncio.to_thread(q.clear_conversation_state, user.id)
    except Exception as e:
        print(f"[ERROR] Exception in start handler: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        raise


# ── Callback query router ──────────────────────────────────────────────────────

async def handle_callback(query: CallbackQuery, bot: Bot) -> None:
    print("[DEBUG] Calling answer_callback_query", flush=True)
    await query.answer()
    data = query.data or ""
    user = query.from_user
    if not user or not query.message:
        return

    chat_id = query.message.chat_id
    msg_id = query.message.message_id

    # Ensure user exists
    try:
        await _db(q.get_user, user.id)
    except Exception:
        await _db(q.upsert_user, user.id, user.username, user.first_name or str(user.id))

    first_name = user.first_name or str(user.id)

    print(f"[DEBUG] Sending response for callback: data={data!r}", flush=True)
    # ── Menu navigation ────────────────────────────────────────────────────────
    if data in ("menu:back", "menu:start"):
        await _db(q.clear_conversation_state, user.id)
        await show_main_menu(bot, chat_id, user.id, first_name, message_id=msg_id)

    elif data == "menu:video":
        await _db(q.clear_conversation_state, user.id)
        await _show_model_list(bot, chat_id, msg_id, "video")

    elif data == "menu:image":
        await _db(q.clear_conversation_state, user.id)
        await _show_model_list(bot, chat_id, msg_id, "image")

    elif data == "menu:balance":
        await _show_balance(bot, chat_id, msg_id, user.id)

    elif data == "menu:history":
        await _show_history(bot, chat_id, msg_id, user.id, offset=0)

    elif data == "menu:credit":
        await _show_credit_packages(bot, chat_id, msg_id)

    elif data == "menu:referral":
        await _show_referral(bot, chat_id, msg_id, user.id, bot)

    elif data == "menu:feedback":
        await bot.edit_message_text(
            "Terima kasih. Hantar maklum balas anda dalam mesej seterusnya atau terus hubungi admin.",
            chat_id=chat_id, message_id=msg_id, reply_markup=back_to_menu_markup(),
        )

    elif data == "menu:language":
        await bot.edit_message_text(
            "Bahasa semasa: Bahasa Melayu.\nTetapan bahasa akan datang.",
            chat_id=chat_id, message_id=msg_id, reply_markup=back_to_menu_markup(),
        )

    elif data == "menu:checkin":
        await _do_checkin(bot, chat_id, msg_id, user.id)

    elif data == "menu:leaderboard":
        await _show_leaderboard(bot, chat_id, msg_id, user.id)

    # ── Generation flow ────────────────────────────────────────────────────────
    elif data.startswith("gen:") and ":model:" in data:
        parts = data.split(":")  # gen, job_type, model, key
        if len(parts) >= 4:
            job_type, model_key = parts[1], parts[3]
            await _select_model(bot, chat_id, msg_id, user.id, job_type, model_key)

    elif data.startswith("gen:") and ":ratio:" in data:
        parts = data.split(":")  # gen, job_type, ratio, <ratio_value may have colon>
        if len(parts) >= 4:
            job_type = parts[1]
            ratio = ":".join(parts[3:])  # handles ratios like "16:9"
            await _select_ratio(bot, chat_id, msg_id, user.id, job_type, ratio)

    elif data.startswith("gen:") and ":back_model" in data:
        job_type = data.split(":")[1]
        await _db(q.clear_conversation_state, user.id)
        await _show_model_list(bot, chat_id, msg_id, job_type)

    elif data.startswith("gen:") and ":back_ratio" in data:
        job_type = data.split(":")[1]
        state = await _db(q.get_conversation_state, user.id)
        model_key = state.get("model_key") if state else None
        if model_key and model_key in MODEL_BY_KEY:
            model = MODEL_BY_KEY[model_key]
            await _show_ratio_selection(bot, chat_id, msg_id, model)
        else:
            await _show_model_list(bot, chat_id, msg_id, job_type)

    elif data == "gen:confirm":
        await _confirm_generation(bot, chat_id, msg_id, user.id)

    elif data == "gen:edit":
        state = await _db(q.get_conversation_state, user.id)
        if state:
            await _db(q.set_conversation_state, user.id, step=AWAIT_INPUT, prompt=None, image_url=None)
            model = MODEL_BY_KEY.get(state.get("model_key", ""))
            job_type = state.get("job_type", "video")
            input_hint = _input_hint(model)
            await bot.edit_message_text(
                input_hint,
                chat_id=chat_id, message_id=msg_id,
                reply_markup=await_input_markup(job_type),
            )

    elif data == "gen:cancel":
        await _db(q.clear_conversation_state, user.id)
        await show_main_menu(bot, chat_id, user.id, first_name, message_id=msg_id)

    # ── History ────────────────────────────────────────────────────────────────
    elif data.startswith("history:"):
        parts = data.split(":")
        offset = int(parts[-1]) if parts[-1].isdigit() else 0
        await _show_history(bot, chat_id, msg_id, user.id, offset=offset)

    # ── Credit / topup ─────────────────────────────────────────────────────────
    elif data.startswith("credit:"):
        pkg_id = int(data.split(":")[1])
        await _create_topup_request(bot, chat_id, msg_id, user.id, pkg_id)

    elif data.startswith("topup:receipt:"):
        request_id = data[len("topup:receipt:"):]
        await _request_receipt(bot, chat_id, msg_id, user.id, request_id)

    elif data.startswith("topup:cancel:"):
        request_id = data[len("topup:cancel:"):]
        await _cancel_topup(bot, chat_id, msg_id, user.id, request_id)

    elif data.startswith("topup:approve:"):
        if not _is_admin(user.id):
            return
        request_id = data[len("topup:approve:"):]
        await _approve_topup(bot, chat_id, msg_id, user.id, request_id, query)

    elif data.startswith("topup:reject:"):
        if not _is_admin(user.id):
            return
        request_id = data[len("topup:reject:"):]
        await _reject_topup(bot, chat_id, msg_id, user.id, request_id, query)


# ── Message router ─────────────────────────────────────────────────────────────

async def handle_photo(message: Message, bot: Bot) -> None:
    """Handle incoming photo — either image input for generation or receipt upload."""
    user = message.from_user
    if not user:
        return

    state = await _db(q.get_conversation_state, user.id)
    step = state.get("step") if state else None

    if step == AWAIT_INPUT:
        await _receive_generation_image(bot, message, user.id, state)
    elif step == AWAIT_RECEIPT:
        await _receive_receipt(bot, message, user.id, state)
    else:
        await message.reply_text(
            "Gunakan menu untuk mula generasi.", reply_markup=back_to_menu_markup()
        )


async def handle_text_message(message: Message, bot: Bot) -> None:
    """Handle incoming plain text — prompt for generation."""
    user = message.from_user
    if not user:
        return

    state = await _db(q.get_conversation_state, user.id)
    step = state.get("step") if state else None

    if step == AWAIT_INPUT:
        await _receive_generation_prompt(bot, message, user.id, state)
    else:
        await message.reply_text(
            "Gunakan menu di bawah untuk mula.", reply_markup=back_to_menu_markup()
        )


# ── Generation flow internals ──────────────────────────────────────────────────

async def _show_model_list(bot: Bot, chat_id: int, msg_id: int, job_type: str) -> None:
    emoji = "🎬" if job_type == "video" else "🖼️"
    label = "Video" if job_type == "video" else "Gambar"
    print(f"[DEBUG] _show_model_list: calling edit_message_text chat_id={chat_id} msg_id={msg_id} job_type={job_type!r}", flush=True)
    try:
        await bot.edit_message_text(
            f"{emoji} Pilih model {label}:",
            chat_id=chat_id, message_id=msg_id,
            reply_markup=model_list_markup(job_type),
        )
        print("[DEBUG] _show_model_list: edit_message_text returned successfully", flush=True)
    except Exception as _e:
        print(f"[ERROR] _show_model_list: edit_message_text failed: {type(_e).__name__}: {_e}", flush=True)
        raise


async def _select_model(
    bot: Bot, chat_id: int, msg_id: int, user_id: int, job_type: str, model_key: str
) -> None:
    model = MODEL_BY_KEY.get(model_key)
    if not model:
        await bot.edit_message_text(
            "Model tidak ditemui.", chat_id=chat_id, message_id=msg_id,
            reply_markup=back_to_menu_markup(),
        )
        return
    await _db(q.set_conversation_state, user_id, step=CHOOSE_RATIO, job_type=job_type, model_key=model_key,
              bot_message_id=msg_id, bot_chat_id=chat_id)
    await _show_ratio_selection(bot, chat_id, msg_id, model)


async def _show_ratio_selection(bot: Bot, chat_id: int, msg_id: int, model) -> None:
    info = (
        f"🔥 <b>{model.display_name}</b>\n\n"
        f"{model.description}\n\n"
        f"💰 Kos: {money(model.sell_price_sen)}\n\n"
        "Pilih nisbah aspek:"
    )
    await bot.edit_message_text(
        info, chat_id=chat_id, message_id=msg_id,
        reply_markup=ratio_markup(model),
        parse_mode=ParseMode.HTML,
    )


async def _select_ratio(
    bot: Bot, chat_id: int, msg_id: int, user_id: int, job_type: str, ratio: str
) -> None:
    state = await _db(q.get_conversation_state, user_id)
    model_key = state.get("model_key") if state else None
    model = MODEL_BY_KEY.get(model_key or "")
    if not model:
        await bot.edit_message_text(
            "Sesi tamat. Sila mula semula.",
            chat_id=chat_id, message_id=msg_id, reply_markup=back_to_menu_markup(),
        )
        return
    if ratio not in model.supported_ratios:
        return
    await _db(q.set_conversation_state, user_id, step=AWAIT_INPUT, ratio=ratio)
    input_hint = _input_hint(model)
    await bot.edit_message_text(
        input_hint, chat_id=chat_id, message_id=msg_id,
        reply_markup=await_input_markup(job_type),
    )


def _input_hint(model) -> str:
    if model is None:
        return "Hantar prompt anda:"
    lines = [f"✏️ <b>Hantar prompt anda</b> (maks {model.max_prompt_chars} aksara):"]
    if model.input_type in ("image_required", "image_optional"):
        if model.input_type == "image_required":
            lines.append("\n📸 <b>Gambar rujukan diperlukan</b> — hantar gambar dahulu, kemudian prompt.")
        else:
            lines.append("\n📸 Gambar rujukan pilihan — hantar gambar (jika mahu), kemudian prompt.")
    if model.prompt_tips:
        lines.append("\n💡 Tips:")
        for tip in model.prompt_tips[:3]:
            lines.append(f"• {tip}")
    return "\n".join(lines)


async def _receive_generation_image(
    bot: Bot, message: Message, user_id: int, state: dict
) -> None:
    model_key = state.get("model_key", "")
    model = MODEL_BY_KEY.get(model_key)
    chat_id = message.chat_id
    msg_id = state.get("bot_message_id")

    # Get file_id from the largest available photo size
    file_id: str | None = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document and message.document.file_name and \
            message.document.file_name.lower().endswith((".jpg", ".jpeg", ".png")):
        if message.document.file_size and message.document.file_size > 10 * 1024 * 1024:
            await message.reply_text("Gambar terlalu besar (maks 10MB).")
            return
        file_id = message.document.file_id

    if not file_id:
        return

    # Download and store temporarily
    try:
        tg_file = await bot.get_file(file_id)
        import tempfile, pathlib
        suffix = ".jpg"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.close()
        await tg_file.download_to_drive(tmp.name)
        uploaded_url = await fal.upload_image(pathlib.Path(tmp.name))
        import os as _os
        _os.unlink(tmp.name)
    except Exception as exc:
        logger.error("Image upload failed: %s", exc)
        await message.reply_text("Gagal muat naik gambar. Cuba lagi.")
        return

    await _db(q.set_conversation_state, user_id, image_url=uploaded_url)

    hint = f"✅ Gambar diterima.\n\n{_input_hint(model)}"
    job_type = state.get("job_type", "video")
    if msg_id and state.get("bot_chat_id"):
        try:
            await bot.edit_message_text(
                hint, chat_id=state["bot_chat_id"], message_id=msg_id,
                reply_markup=await_input_markup(job_type), parse_mode=ParseMode.HTML,
            )
            await message.delete()
            return
        except Exception:
            pass
    await message.reply_text(hint, reply_markup=await_input_markup(job_type), parse_mode=ParseMode.HTML)


async def _receive_generation_prompt(
    bot: Bot, message: Message, user_id: int, state: dict
) -> None:
    model_key = state.get("model_key", "")
    model = MODEL_BY_KEY.get(model_key)
    chat_id = message.chat_id
    msg_id = state.get("bot_message_id")
    job_type = state.get("job_type", "video")
    prompt = (message.text or "").strip()

    if model and len(prompt) > model.max_prompt_chars:
        await message.reply_text(
            f"Prompt terlalu panjang ({len(prompt)} aksara, maks {model.max_prompt_chars})."
        )
        return
    if len(prompt) < 3:
        await message.reply_text("Prompt terlalu pendek (maks 3 aksara).")
        return

    # Check image requirement
    image_url = state.get("image_url")
    if model and model.input_type == "image_required" and not image_url:
        await message.reply_text(
            "📸 Model ini memerlukan gambar rujukan. Sila hantar gambar dahulu."
        )
        return

    # Check balance
    if model and not await _db(credit.can_afford, user_id, model.sell_price_sen):
        user = await _db(q.get_user, user_id)
        await message.reply_text(
            f"❌ Baki tidak mencukupi. Baki semasa: {money(int(user['balance']))}.\n"
            f"Kos generasi: {money(model.sell_price_sen)}.",
            reply_markup=back_to_menu_markup(),
        )
        return

    await _db(q.set_conversation_state, user_id, step=CONFIRM, prompt=prompt)

    confirm_text = _confirm_card(model, prompt, image_url, state.get("ratio", ""))
    markup = confirm_markup()
    if msg_id and state.get("bot_chat_id"):
        try:
            await bot.edit_message_text(
                confirm_text, chat_id=state["bot_chat_id"], message_id=msg_id,
                reply_markup=markup, parse_mode=ParseMode.HTML,
            )
            await message.delete()
            return
        except Exception:
            pass
    sent = await message.reply_text(confirm_text, reply_markup=markup, parse_mode=ParseMode.HTML)
    await _db(q.set_conversation_state, user_id, bot_message_id=sent.message_id, bot_chat_id=chat_id)


def _confirm_card(model, prompt: str, image_url: str | None, ratio: str) -> str:
    model_name = model.display_name if model else "?"
    cost = money(model.sell_price_sen) if model else "?"
    lines = [
        "📋 <b>Ringkasan Generasi</b>",
        "",
        f"Model: {model_name}",
        f"Nisbah: {ratio}",
        f"Prompt: {prompt[:200]}{'…' if len(prompt) > 200 else ''}",
    ]
    if image_url:
        lines.append("Gambar rujukan: ✅")
    lines += ["", f"💰 Kos: {cost}", "", "Teruskan?"]
    return "\n".join(lines)


async def _confirm_generation(bot: Bot, chat_id: int, msg_id: int, user_id: int) -> None:
    state = await _db(q.get_conversation_state, user_id)
    if not state or state.get("step") != CONFIRM:
        await bot.edit_message_text(
            "Sesi tamat. Sila mula semula.",
            chat_id=chat_id, message_id=msg_id, reply_markup=back_to_menu_markup(),
        )
        return

    model_key = state.get("model_key", "")
    model = MODEL_BY_KEY.get(model_key)
    if not model:
        await bot.edit_message_text(
            "Model tidak ditemui.", chat_id=chat_id, message_id=msg_id,
            reply_markup=back_to_menu_markup(),
        )
        return

    prompt = state.get("prompt", "")
    image_url = state.get("image_url")
    ratio = state.get("ratio", model.supported_ratios[0])

    # Double-check balance
    if not await _db(credit.can_afford, user_id, model.sell_price_sen):
        user = await _db(q.get_user, user_id)
        await bot.edit_message_text(
            f"❌ Baki tidak mencukupi ({money(int(user['balance']))}).",
            chat_id=chat_id, message_id=msg_id, reply_markup=back_to_menu_markup(),
        )
        return

    await bot.edit_message_text(
        "⏳ Menghantar ke fal.ai…",
        chat_id=chat_id, message_id=msg_id, reply_markup=None,
    )

    job_id = uuid4().hex
    try:
        await _db(credit.debit, user_id, model.sell_price_sen, job_id)
    except Exception as exc:
        await bot.edit_message_text(
            f"❌ Gagal debit kredit: {exc}",
            chat_id=chat_id, message_id=msg_id, reply_markup=back_to_menu_markup(),
        )
        return

    # Build fal arguments
    arguments: dict = {"prompt": prompt}
    if image_url:
        arguments["image_url"] = image_url
    extra = model.ratio_to_dimension_map.get(ratio, {})
    arguments.update(extra)

    try:
        # Submit to fal.ai and get request_id + polling handle (no webhook needed).
        request_id, fal_handle = await fal.submit_job(model.fal_endpoint, arguments)
        await _db(
            q.create_job,
            job_id, user_id, model.key, model.job_type, prompt, model.sell_price_sen,
            image_url, fal_request_id=request_id, status="processing",
        )
    except Exception as exc:
        logger.exception("fal.ai submit failed for job %s", job_id)
        await _db(credit.refund, user_id, model.sell_price_sen, f"refund:{job_id}")
        await bot.edit_message_text(
            f"❌ Gagal menghantar ke fal.ai: {exc}",
            chat_id=chat_id, message_id=msg_id, reply_markup=back_to_menu_markup(),
        )
        return

    # Settle referral on first-ever generation
    try:
        await _db(q.settle_referral, user_id, _referral_bonus())
    except Exception:
        pass

    await _db(q.clear_conversation_state, user_id)

    user = await _db(q.get_user, user_id)
    await bot.edit_message_text(
        f"⏳ Sedang menjana... ID: <code>{job_id[:8]}</code>\n"
        f"Baki selepas: {money(int(user['balance']))}\n\n"
        "Hasil akan dihantar terus apabila siap.",
        chat_id=chat_id, message_id=msg_id,
        reply_markup=back_to_menu_markup(),
        parse_mode=ParseMode.HTML,
    )

    # Spawn background task: poll fal.ai and deliver result to the user.
    asyncio.create_task(
        _poll_and_deliver(bot, chat_id, user_id, job_id, model, fal_handle)
    )


# ── Background generation task ────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _poll_and_deliver(
    bot: Bot,
    chat_id: int,
    user_id: int,
    job_id: str,
    model,
    fal_handle,
) -> None:
    """Poll fal.ai for the result and send it to the user when ready."""
    try:
        result = await fal.wait_for_result(fal_handle)
        output_url = fal.extract_output_url(result, model.job_type)
        await _db(q.update_job, job_id, status="completed", output_url=output_url,
                  completed_at=_utc_now())

        short_id = f"Job <code>{job_id[:8]}</code>"
        if model.job_type == "video":
            await bot.send_video(
                chat_id, output_url,
                caption=f"✅ Video siap! {short_id}",
                reply_markup=back_to_menu_markup(),
                parse_mode=ParseMode.HTML,
            )
        else:
            await bot.send_photo(
                chat_id, output_url,
                caption=f"✅ Gambar siap! {short_id}",
                reply_markup=back_to_menu_markup(),
                parse_mode=ParseMode.HTML,
            )
    except Exception as exc:
        logger.exception("Generation failed for job %s: %s", job_id, exc)
        try:
            await _db(q.update_job, job_id, status="failed")
        except Exception:
            pass
        try:
            await _db(credit.refund, user_id, model.sell_price_sen, f"refund:{job_id}")
        except Exception:
            pass
        try:
            await bot.send_message(
                chat_id,
                f"❌ Generasi gagal. Kredit telah dipulangkan.\nRalat: {exc}",
                reply_markup=back_to_menu_markup(),
            )
        except Exception:
            pass


# ── Balance ────────────────────────────────────────────────────────────────────

async def _show_balance(bot: Bot, chat_id: int, msg_id: int, user_id: int) -> None:
    user, txns = await asyncio.gather(
        _db(q.get_user, user_id),
        _db(q.recent_transactions, user_id),
    )
    lines = [
        f"{t['created_at'][:10]} · {t['type']} · "
        f"{'+' if t['amount'] >= 0 else ''}{money(int(t['amount']))}"
        for t in txns
    ]
    await bot.edit_message_text(
        f"Baki semasa: {money(int(user['balance']))}\n\n"
        "Transaksi terakhir:\n" + ("\n".join(lines) or "Belum ada transaksi."),
        chat_id=chat_id, message_id=msg_id, reply_markup=back_to_menu_markup(),
    )


# ── History ────────────────────────────────────────────────────────────────────

async def _show_history(bot: Bot, chat_id: int, msg_id: int, user_id: int, offset: int) -> None:
    jobs = await _db(q.recent_jobs, user_id, offset=offset)
    if not jobs:
        text = "Belum ada sejarah generasi."
    else:
        lines = []
        for job in jobs:
            model = MODEL_BY_KEY.get(job["model_key"])
            label = model.display_name if model else job["model_key"]
            lines.append(f"• {label} · {job['status']} · {job['created_at'][:16]}")
        text = "Sejarah generasi:\n\n" + "\n".join(lines)
    await bot.edit_message_text(
        text, chat_id=chat_id, message_id=msg_id,
        reply_markup=history_markup(offset, has_more=len(jobs) == 8),
    )


# ── Referral ───────────────────────────────────────────────────────────────────

async def _show_referral(bot: Bot, chat_id: int, msg_id: int, user_id: int, tg_bot: Bot) -> None:
    try:
        me = await tg_bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{user_id}"
    except Exception:
        link = f"ref_{user_id}"
    await bot.edit_message_text(
        "Ajak kawan dan dapat bonus kredit apabila mereka mula menjana.\n\n"
        f"Link anda:\n{link}\n\n"
        f"Bonus: {money(_referral_bonus())} untuk anda dan kawan.",
        chat_id=chat_id, message_id=msg_id, reply_markup=back_to_menu_markup(),
    )


# ── Check-in ───────────────────────────────────────────────────────────────────

async def _do_checkin(bot: Bot, chat_id: int, msg_id: int, user_id: int) -> None:
    result = await _db(q.checkin, user_id, _checkin_bonus())
    if result is None:
        user = await _db(q.get_user, user_id)
        last = user.get("last_checkin", "")
        next_dt = "minggu depan"
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=UTC)
                next_dt = (last_dt + timedelta(days=7)).strftime("%d/%m/%Y")
            except Exception:
                pass
        await bot.edit_message_text(
            f"Anda sudah check-in minggu ini. Check-in seterusnya pada {next_dt}.",
            chat_id=chat_id, message_id=msg_id, reply_markup=back_to_menu_markup(),
        )
    else:
        await bot.edit_message_text(
            f"✅ Check-in berjaya! Bonus {money(_checkin_bonus())} dikreditkan.\n"
            f"Baki sekarang: {money(result)}.",
            chat_id=chat_id, message_id=msg_id, reply_markup=back_to_menu_markup(),
        )


# ── Leaderboard ────────────────────────────────────────────────────────────────

async def _show_leaderboard(bot: Bot, chat_id: int, msg_id: int, user_id: int) -> None:
    rows = await _db(q.leaderboard)
    if not rows:
        text = "Papan pendahulu kosong buat masa ini."
    else:
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        lines = []
        for i, row in enumerate(rows):
            medal = medals[i] if i < len(medals) else "•"
            uid = row["user_id"]
            you = " (anda)" if uid == user_id else ""
            lines.append(f"{medal} User {uid}{you} — {row['completed']} generasi")
        text = "🏆 Papan Pendahulu\n\n" + "\n".join(lines)
    await bot.edit_message_text(
        text, chat_id=chat_id, message_id=msg_id, reply_markup=back_to_menu_markup(),
    )


# ── Credit packages ────────────────────────────────────────────────────────────

async def _show_credit_packages(bot: Bot, chat_id: int, msg_id: int) -> None:
    packages = await _db(q.get_credit_packages)
    if not packages:
        await bot.edit_message_text(
            "Tiada pakej kredit tersedia buat masa ini.",
            chat_id=chat_id, message_id=msg_id, reply_markup=back_to_menu_markup(),
        )
        return
    await bot.edit_message_text(
        "Pilih pakej kredit:",
        chat_id=chat_id, message_id=msg_id,
        reply_markup=packages_markup(packages),
    )


async def _create_topup_request(
    bot: Bot, chat_id: int, msg_id: int, user_id: int, pkg_id: int
) -> None:
    try:
        pkg, settings = await asyncio.gather(
            _db(q.get_credit_package, pkg_id),
            _db(q.get_payment_settings),
        )
    except KeyError:
        await bot.edit_message_text(
            "Pakej tidak ditemui.", chat_id=chat_id, message_id=msg_id,
            reply_markup=back_to_menu_markup(),
        )
        return

    expiry_minutes = settings["payment_expiry_minutes"] if settings else 30
    instructions = settings["payment_instructions"] if settings and settings.get("payment_instructions") else "Bayar jumlah yang ditetapkan."
    qr_url = settings["qr_image_url"] if settings else None

    from datetime import UTC, datetime, timedelta
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=expiry_minutes)
    request_id = uuid4().hex

    await _db(q.create_topup_request,
        request_id=request_id,
        user_id=user_id,
        package_id=pkg_id,
        amount_rm=float(pkg["price_rm"]),
        bonus_percent=pkg["bonus_percent"],
        created_at=now.isoformat(),
        expires_at=expires_at.isoformat(),
    )
    await _db(q.set_conversation_state, user_id, topup_request_id=request_id)

    pkg_label = f"{pkg['name']} — RM {pkg['price_rm']:.2f}"
    if pkg["bonus_percent"]:
        pkg_label += f" (+{pkg['bonus_percent']}% bonus)"

    text = (
        f"💳 <b>Permintaan Top-up</b>\n\n"
        f"Pakej: {pkg_label}\n"
        f"Jumlah: RM {pkg['price_rm']:.2f}\n"
        f"Tamat: {expires_at.strftime('%d/%m/%Y %H:%M')} UTC\n\n"
        f"{instructions}"
    )

    if qr_url:
        try:
            await bot.send_photo(chat_id, qr_url, caption=text,
                                 reply_markup=topup_action_markup(request_id),
                                 parse_mode=ParseMode.HTML)
            try:
                await bot.delete_message(chat_id, msg_id)
            except Exception:
                pass
            return
        except Exception:
            pass

    await bot.edit_message_text(
        text, chat_id=chat_id, message_id=msg_id,
        reply_markup=topup_action_markup(request_id),
        parse_mode=ParseMode.HTML,
    )


async def _request_receipt(
    bot: Bot, chat_id: int, msg_id: int, user_id: int, request_id: str
) -> None:
    try:
        req = await _db(q.get_topup_request, request_id)
    except KeyError:
        await bot.edit_message_text(
            "Permintaan tidak ditemui.", chat_id=chat_id, message_id=msg_id,
            reply_markup=back_to_menu_markup(),
        )
        return
    if req["status"] != "awaiting_receipt":
        await bot.edit_message_text(
            f"Status semasa: {req['status']}.",
            chat_id=chat_id, message_id=msg_id, reply_markup=back_to_menu_markup(),
        )
        return
    await _db(q.set_conversation_state, user_id, step=AWAIT_RECEIPT, topup_request_id=request_id)
    await bot.edit_message_text(
        "📤 Sila hantar gambar resit pembayaran sekarang.",
        chat_id=chat_id, message_id=msg_id, reply_markup=back_to_menu_markup(),
    )


async def _receive_receipt(bot: Bot, message: Message, user_id: int, state: dict) -> None:
    request_id = state.get("topup_request_id")
    if not request_id:
        await message.reply_text("Tiada permintaan aktif.", reply_markup=back_to_menu_markup())
        return

    try:
        req = await _db(q.get_topup_request, request_id)
    except KeyError:
        await message.reply_text("Permintaan tidak ditemui.", reply_markup=back_to_menu_markup())
        return

    if req["status"] != "awaiting_receipt":
        await message.reply_text(f"Status: {req['status']}.", reply_markup=back_to_menu_markup())
        return

    file_id: str | None = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        file_id = message.document.file_id

    if not file_id:
        await message.reply_text("Sila hantar gambar resit.")
        return

    await _db(q.update_topup_request, request_id, status="pending_review", receipt_file_id=file_id)
    await _db(q.clear_conversation_state, user_id)

    # Append admin-away notice if active
    settings = await _db(q.get_app_settings)
    away_suffix = ""
    if settings.get("admin_away_mode"):
        away_msg = (settings.get("admin_away_message") or "").strip()
        if away_msg:
            away_suffix = f"\n\nℹ️ {away_msg}"

    await message.reply_text(
        f"✅ Resit diterima. Admin akan menyemak dalam masa terdekat.{away_suffix}",
        reply_markup=back_to_menu_markup(),
    )

    # Notify admin
    admin_chat = _admin_chat_id()
    if admin_chat:
        pkg = await _db(q.get_credit_package, req["package_id"])
        caption = (
            f"📥 Resit top-up baharu\n"
            f"User: {user_id}\n"
            f"Pakej: {pkg['name']} — RM {req['amount_rm']:.2f}\n"
            f"Request ID: <code>{request_id}</code>"
        )
        try:
            await bot.send_photo(
                admin_chat, file_id, caption=caption,
                reply_markup=admin_review_markup(request_id),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


async def _cancel_topup(
    bot: Bot, chat_id: int, msg_id: int, user_id: int, request_id: str
) -> None:
    try:
        req = await _db(q.get_topup_request, request_id)
        if req["status"] in ("awaiting_receipt", "pending_review"):
            await _db(q.update_topup_request, request_id, status="cancelled")
    except Exception:
        pass
    await _db(q.clear_conversation_state, user_id)
    await show_main_menu(bot, chat_id, user_id, "", message_id=msg_id)


# ── Admin topup actions ────────────────────────────────────────────────────────

async def _approve_topup(
    bot: Bot, chat_id: int, msg_id: int, admin_id: int, request_id: str, query: CallbackQuery
) -> None:
    try:
        user_id, new_balance, amount_rm, bonus_pct, pkg_name = await _db(q.approve_topup, request_id, admin_id)
    except Exception as exc:
        await query.answer(f"Gagal: {exc}", show_alert=True)
        return
    admin_name = query.from_user.first_name if query.from_user else str(admin_id)
    try:
        old = query.message.caption or query.message.text or ""
        if query.message.caption is not None:
            await query.edit_message_caption(
                caption=f"{old}\n\n✅ Diluluskan oleh {admin_name}", reply_markup=None
            )
        else:
            await query.edit_message_text(
                f"{old}\n\n✅ Diluluskan oleh {admin_name}", reply_markup=None
            )
    except Exception:
        pass
    try:
        await bot.send_message(
            user_id,
            f"✅ Top-up diluluskan!\nPakej: {pkg_name}\n"
            f"Jumlah: RM {amount_rm:.2f}"
            + (f" (+{bonus_pct}% bonus)" if bonus_pct else "")
            + f"\nBaki baru: {money(new_balance)}",
        )
    except Exception:
        pass


async def _reject_topup(
    bot: Bot, chat_id: int, msg_id: int, admin_id: int, request_id: str, query: CallbackQuery
) -> None:
    try:
        user_id, pkg_name = await _db(q.reject_topup, request_id, admin_id)
    except Exception as exc:
        await query.answer(f"Gagal: {exc}", show_alert=True)
        return
    admin_name = query.from_user.first_name if query.from_user else str(admin_id)
    try:
        old = query.message.caption or query.message.text or ""
        if query.message.caption is not None:
            await query.edit_message_caption(
                caption=f"{old}\n\n❌ Ditolak oleh {admin_name}", reply_markup=None
            )
        else:
            await query.edit_message_text(
                f"{old}\n\n❌ Ditolak oleh {admin_name}", reply_markup=None
            )
    except Exception:
        pass
    try:
        await bot.send_message(
            user_id, "❌ Pembayaran tidak dapat disahkan. Sila hubungi admin atau cuba semula."
        )
    except Exception:
        pass


# ── Admin commands ─────────────────────────────────────────────────────────────

async def handle_command(message: Message, bot: Bot) -> None:
    user = message.from_user
    if not user:
        return
    text = message.text or ""
    cmd = text.split()[0].lower().lstrip("/").split("@")[0]
    args = text.split()[1:]

    if cmd == "start":
        await handle_start(message, bot)
        return

    if cmd == "addcredit":
        if not _is_admin(user.id):
            return
        if len(args) != 2:
            await message.reply_text("Guna: /addcredit USER_ID JUMLAH_SEN")
            return
        try:
            target_id, amount = int(args[0]), int(args[1])
            new_bal = await _db(q.mutate_balance, target_id, amount, "admin_adjust", f"admin:{user.id}")
            await message.reply_text(f"Baki user {target_id}: {money(new_bal)}")
        except Exception as exc:
            await message.reply_text(f"Gagal: {exc}")
        return

    if cmd == "stats":
        if not _is_admin(user.id):
            return
        stats = await _db(q.admin_stats)
        await message.reply_text(
            f"Users: {stats['users']}\nJobs: {stats['jobs']}\n"
            f"Completed: {stats['completed']}\nSpent: {money(stats['spent'])}"
        )
        return

    if cmd == "broadcast":
        if not _is_admin(user.id):
            return
        msg_text = " ".join(args).strip()
        if not msg_text:
            await message.reply_text("Guna: /broadcast mesej")
            return
        ids = await _db(q.all_user_ids)
        sent = 0
        for uid in ids:
            try:
                await bot.send_message(uid, msg_text)
                sent += 1
            except Exception:
                continue
        await message.reply_text(f"Broadcast dihantar kepada {sent}/{len(ids)} pengguna.")
        return

    # Unknown command — show menu
    await message.reply_text(
        "Guna menu di bawah:", reply_markup=back_to_menu_markup()
    )
