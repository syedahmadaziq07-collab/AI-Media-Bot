# JagoVideo Clone

Telegram bot AI video/image generation service built with Python, `python-telegram-bot`, SQLite, and fal.ai.

## How to run

```bash
uv run bot.py
```

The workflow **JagoVideo Clone Bot** is already configured and uses this command.

## Required secrets

| Secret | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `FAL_KEY` | API key from [fal.ai](https://fal.ai) |

## Optional settings (via Replit Secrets or `.env`)

| Variable | Default | Description |
|---|---|---|
| `DATABASE_PATH` | `data/jagovideo.sqlite3` | SQLite database path |
| `ADMIN_USER_IDS` | *(empty)* | Comma-separated Telegram user IDs with admin access |
| `PAYMENT_GATEWAY_KEY` | *(empty)* | Payment gateway secret (use `/addcredit USER_ID AMOUNT` for local testing) |
| `BOT_NAME` | `JagoVideo Clone` | Display name shown in the bot |
| `CHECKIN_BONUS` | `50` | Credits awarded for weekly check-in (in sen) |
| `REFERRAL_BONUS` | `100` | Credits awarded per referral (in sen) |

## Stack

- **Runtime**: Python 3.11+, managed by `uv`
- **Bot framework**: `python-telegram-bot` 21+
- **AI provider**: fal.ai (`fal-client`)
- **Database**: SQLite via `aiosqlite`
- **Handlers**: `handlers/` — per-feature conversation handlers
- **Services**: `services/` — credit, generation, fal.ai, payment logic

## Admin commands

- `/addcredit USER_ID AMOUNT` — add credits (in sen) to a user's balance
- Other admin handlers are registered in `handlers/admin.py`

## User preferences
