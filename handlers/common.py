from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from models_config import MODELS


def main_menu_markup() -> InlineKeyboardMarkup:
    """2-column InlineKeyboardMarkup for the main menu."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 Buat Video",        callback_data="menu:video"),
            InlineKeyboardButton("🖼️ Buat Gambar",       callback_data="menu:image"),
        ],
        [
            InlineKeyboardButton("💳 Kredit",            callback_data="menu:credit"),
            InlineKeyboardButton("👥 Ajak Kawan",        callback_data="menu:referral"),
        ],
        [
            InlineKeyboardButton("💰 Baki Saya",         callback_data="menu:balance"),
            InlineKeyboardButton("📋 Sejarah",           callback_data="menu:history"),
        ],
        [
            InlineKeyboardButton("📝 Maklum Balas",      callback_data="menu:feedback"),
            InlineKeyboardButton("🌐 Bahasa",            callback_data="menu:language"),
        ],
        [
            InlineKeyboardButton("✅ Check-in Mingguan", callback_data="menu:checkin"),
            InlineKeyboardButton("🏆 Papan Pendahulu",   callback_data="menu:leaderboard"),
        ],
    ])


def back_to_menu_button() -> InlineKeyboardMarkup:
    """Single-button markup that returns the user to the main menu."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("◀️ Menu Utama", callback_data="menu:back")]]
    )


def back_button(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("◀️ Kembali", callback_data=callback_data)]]
    )


def money(sen: int) -> str:
    return f"RM {sen / 100:.2f}"


def get_services(context):
    data = context.application.bot_data
    return data["db"], data["generation"], data["credit"], data["payment"]


async def build_menu_message(context, user_id: int, first_name: str) -> tuple[str, InlineKeyboardMarkup]:
    """Fetch live balance/stats and return (text, markup) for the main menu."""
    db = context.application.bot_data["db"]
    user = await db.get_user(user_id)
    stats = await db.user_stats(user_id)
    groups: dict[str, list[str]] = {}
    for model in MODELS:
        groups.setdefault(model.server_group, []).append(model.display_name)
    model_text = "\n".join(
        f"• {group}: {', '.join(names)}" for group, names in groups.items()
    )
    text = (
        f"Selamat datang ke JagoVideo Clone, {first_name}.\n\n"
        f"Baki kredit: {money(int(user['balance']))}\n"
        f"Generasi: {stats['completed']} siap / {stats['total']} jumlah\n\n"
        f"Model tersedia:\n{model_text}\n\n"
        "Pilih apa yang anda mahu buat:"
    )
    return text, main_menu_markup()
