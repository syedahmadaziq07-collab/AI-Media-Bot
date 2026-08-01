"""InlineKeyboardMarkup builders for all bot flows."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from models_config import AIModel, MODELS, models_for


# ── Utilities ──────────────────────────────────────────────────────────────────

def money(sen: int) -> str:
    return f"RM {sen / 100:.2f}"


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


# ── Shared ─────────────────────────────────────────────────────────────────────

def main_menu_markup() -> InlineKeyboardMarkup:
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


def back_to_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("◀️ Menu Utama", callback_data="menu:back")]]
    )


def back_markup(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("◀️ Kembali", callback_data=callback_data)]]
    )


# ── Generation flow ────────────────────────────────────────────────────────────

def model_list_markup(job_type: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            f"{m.display_name} · {money(m.sell_price_sen)}",
            callback_data=f"gen:{job_type}:model:{m.key}",
        )]
        for m in models_for(job_type)
    ]
    rows.append([InlineKeyboardButton("◀️ Kembali", callback_data="gen:cancel")])
    return InlineKeyboardMarkup(rows)


def ratio_markup(model: AIModel) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            f"{_ratio_icon(r)} {r}",
            callback_data=f"gen:{model.job_type}:ratio:{r}",
        )]
        for r in model.supported_ratios
    ]
    rows.append([InlineKeyboardButton(
        "◀️ Kembali", callback_data=f"gen:{model.job_type}:back_model"
    )])
    return InlineKeyboardMarkup(rows)


def await_input_markup(job_type: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("◀️ Kembali", callback_data=f"gen:{job_type}:back_ratio")]]
    )


def confirm_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Jana",    callback_data="gen:confirm"),
            InlineKeyboardButton("✏️ Ubah",   callback_data="gen:edit"),
        ],
        [InlineKeyboardButton("❌ Batal", callback_data="gen:cancel")],
    ])


# ── History ────────────────────────────────────────────────────────────────────

def history_markup(offset: int, has_more: bool) -> InlineKeyboardMarkup:
    nav = []
    if offset >= 8:
        nav.append(InlineKeyboardButton("Sebelumnya", callback_data=f"history:prev:{offset - 8}"))
    if has_more:
        nav.append(InlineKeyboardButton("Seterusnya", callback_data=f"history:next:{offset + 8}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton("◀️ Menu Utama", callback_data="menu:back")])
    return InlineKeyboardMarkup(rows)


# ── Credit / topup ─────────────────────────────────────────────────────────────

def packages_markup(packages: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for pkg in packages:
        label = f"{pkg['name']} — RM {pkg['price_rm']:.2f}"
        if pkg["bonus_percent"]:
            label += f" (+{pkg['bonus_percent']}% bonus)"
        rows.append([InlineKeyboardButton(label, callback_data=f"credit:{pkg['id']}")])
    rows.append([InlineKeyboardButton("◀️ Menu Utama", callback_data="menu:back")])
    return InlineKeyboardMarkup(rows)


def topup_action_markup(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Hantar Resit", callback_data=f"topup:receipt:{request_id}")],
        [InlineKeyboardButton("❌ Batal",        callback_data=f"topup:cancel:{request_id}")],
        [InlineKeyboardButton("◀️ Menu Utama",   callback_data="menu:back")],
    ])


def admin_review_markup(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Lulus",  callback_data=f"topup:approve:{request_id}"),
            InlineKeyboardButton("❌ Tolak",  callback_data=f"topup:reject:{request_id}"),
        ]
    ])
