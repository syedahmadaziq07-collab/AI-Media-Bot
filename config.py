"""Runtime configuration for JagoVideo Clone."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    fal_key: str
    database_path: Path
    admin_user_ids: frozenset[int]
    payment_gateway_key: str | None
    bot_name: str
    checkin_bonus: int
    referral_bonus: int


def _admin_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if item:
            try:
                ids.add(int(item))
            except ValueError as exc:
                raise ValueError(f"Invalid admin user id: {item}") from exc
    return frozenset(ids)


def load_settings() -> Settings:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    fal_key = os.getenv("FAL_KEY", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing.")
    if not fal_key:
        raise RuntimeError("FAL_KEY is missing.")

    return Settings(
        telegram_bot_token=token,
        fal_key=fal_key,
        database_path=Path(os.getenv("DATABASE_PATH", "data/jagovideo.sqlite3")),
        admin_user_ids=_admin_ids(os.getenv("ADMIN_USER_IDS", "")),
        payment_gateway_key=os.getenv("PAYMENT_GATEWAY_KEY") or None,
        bot_name=os.getenv("BOT_NAME", "JagoVideo Clone"),
        checkin_bonus=int(os.getenv("CHECKIN_BONUS", "50")),
        referral_bonus=int(os.getenv("REFERRAL_BONUS", "100")),
    )