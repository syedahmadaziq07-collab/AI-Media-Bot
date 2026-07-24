from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

MAIN_MENU = [
    ["Buat Video", "Buat Gambar"],
    ["Kredit", "Baki Saya"],
    ["Ajak Kawan", "Sejarah"],
    ["Maklum Balas", "Bahasa"],
    ["Check-in Mingguan", "Papan Pendahulu"],
]


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True, is_persistent=True)


def back_button(callback_data: str = "menu:back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Kembali", callback_data=callback_data)]])


def service(db):
    return db


def money(sen: int) -> str:
    return f"RM {sen / 100:.2f}"


def get_services(context):
    data = context.application.bot_data
    return data["db"], data["generation"], data["credit"], data["payment"]