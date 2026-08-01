---
name: JagoVideo bot architecture
description: Key design decisions, file layout, and sharp edges for the JagoVideo Clone Telegram bot.
---

## Stack
- Python 3.11, python-telegram-bot v22 (async), aiosqlite, fal-client v1.0, python-dotenv
- Entry point: `bot.py` — sets up Application, registers all handlers, runs polling
- Run command: `uv run bot.py` (workflow: "JagoVideo Clone Bot")
- SQLite DB path from env `DATABASE_PATH` (default `data/jagovideo.db`)

## Key decisions

**Debit-before-submit pattern:** Credit is deducted atomically (with `BEGIN IMMEDIATE`) before the fal.ai job is submitted. Refund happens automatically in `_poll()` on failure. Never debit after job completes — race condition risk.

**Balance stored as integers (sen):** Avoids float precision errors. RM 1.00 = 100 sen.

**Non-blocking generation polling:** `generation.start()` spawns `asyncio.create_task(_poll(...))` so Telegram's event loop is never blocked during fal.ai polling.

**Aspect ratio flow:** After model selection, `CHOOSE_RATIO` state shows an info card + ratio keyboard. The selected ratio maps to fal.ai-specific parameters via `AIModel.ratio_to_dimension_map` (merged as `extra_args` into the fal.ai payload). Different endpoints use different schema — video models use `{"aspect_ratio": "16:9"}`, image models use `{"image_size": {"width": ..., "height": ...}}`.

**ConversationHandler states:** `CHOOSE_MODEL → CHOOSE_RATIO → AWAIT_IMAGE (optional) → AWAIT_PROMPT → CONFIRM`. Back buttons at each state go exactly one step back, not to main menu.

## File layout
```
bot.py                    # entry point, Application setup
config.py                 # Settings dataclass, load_settings()
models_config.py          # AIModel catalog with ratio_to_dimension_map
database/
  db.py                   # Database class, all SQL, atomic balance mutations
  models.py               # (reserved for future ORM models)
  queries.py              # (reserved)
handlers/
  generation_flow.py      # ConversationHandler for video+image (shared)
  start.py                # /start, welcome, main menu
  balance.py              # "Baki Saya"
  credit.py               # top-up packages, payment placeholder
  history.py              # job history with pagination
  referral.py             # referral deep link
  settings.py             # language, feedback, check-in, leaderboard
  admin.py                # /broadcast, /addcredit, /stats
  common.py               # shared helpers (get_services, money, main_keyboard)
services/
  fal_service.py          # fal-client wrapper (upload, submit, poll)
  generation_service.py   # orchestration: debit, upload, submit, poll, refund
  credit_service.py       # debit/refund helpers
  payment_service.py      # placeholder payment gateway stub
```

## Sharp edges
- `aiosqlite` requires explicit cursor fetching — see sqlite-async-cursors.md
- `PAYMENT_GATEWAY_KEY` is a placeholder — payment top-up is not functional until a real gateway is wired into `services/payment_service.py`
- `ADMIN_USER_IDS` in env is comma-separated integers
- fal.ai endpoint schemas differ per model — always check `ratio_to_dimension_map` when adding new models
- PTBUserWarning about `per_message=False` on ConversationHandler is expected and harmless
