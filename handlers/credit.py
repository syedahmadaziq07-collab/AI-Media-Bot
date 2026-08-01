from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from .common import back_to_menu_button, get_services


async def show_credit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    await update.callback_query.answer()
    db, *_ = get_services(context)
    packages = await db.get_credit_packages()
    if not packages:
        await update.callback_query.edit_message_text(
            "Tiada pakej kredit tersedia buat masa ini.",
            reply_markup=back_to_menu_button(),
        )
        return
    rows = []
    for pkg in packages:
        label = f"{pkg['name']} — RM {pkg['price_rm']:.2f}"
        if pkg["bonus_percent"]:
            label += f" (+{pkg['bonus_percent']}% bonus)"
        rows.append([InlineKeyboardButton(label, callback_data=f"credit:{pkg['id']}")])
    rows.append([InlineKeyboardButton("◀️ Menu Utama", callback_data="menu:back")])
    await update.callback_query.edit_message_text(
        "Pilih pakej kredit:",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def choose_credit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()

    try:
        pkg_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.edit_message_text("Ralat. Sila cuba semula.", reply_markup=back_to_menu_button())
        return

    db, *_ = get_services(context)

    try:
        pkg = await db.get_credit_package(pkg_id)
    except KeyError:
        await query.edit_message_text("Pakej tidak ditemui.", reply_markup=back_to_menu_button())
        return

    settings_row = await db.get_payment_settings()
    expiry_minutes = settings_row["payment_expiry_minutes"] if settings_row else 30
    instructions = (
        settings_row["payment_instructions"]
        if settings_row and settings_row["payment_instructions"]
        else "Bayar jumlah yang ditetapkan."
    )
    qr_url = settings_row["qr_image_url"] if settings_row else None

    # Create topup request
    request_id = uuid4().hex
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=expiry_minutes)

    await db.create_topup_request(
        request_id=request_id,
        user_id=update.effective_user.id,
        package_id=pkg_id,
        amount_rm=pkg["price_rm"],
        bonus_percent=pkg["bonus_percent"],
        created_at=now.isoformat(),
        expires_at=expires_at.isoformat(),
    )

    expires_str = expires_at.strftime("%d/%m/%Y %H:%M UTC")
    pkg_label = f"{pkg['name']} — RM {pkg['price_rm']:.2f}"
    if pkg["bonus_percent"]:
        pkg_label += f" (+{pkg['bonus_percent']}% bonus)"

    body = (
        f"{instructions}\n\n"
        f"📦 {pkg_label}\n"
        f"⏰ Tamat: {expires_str}"
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Hantar Resit Pembayaran", callback_data=f"topup:receipt:{request_id}")],
        [InlineKeyboardButton("❌ Batalkan",               callback_data=f"topup:cancel:{request_id}")],
        [InlineKeyboardButton("◀️ Kembali",               callback_data="menu:credit")],
    ])

    if qr_url:
        # Send QR as a new photo message; edit current message to acknowledge
        try:
            await query.message.reply_photo(photo=qr_url, caption=body, reply_markup=markup)
            await query.edit_message_text("Gambar QR dihantar. Semak mesej di bawah.")
        except Exception:
            # Fallback: show without QR
            await query.edit_message_text(body, reply_markup=markup)
    else:
        await query.edit_message_text(body, reply_markup=markup)
