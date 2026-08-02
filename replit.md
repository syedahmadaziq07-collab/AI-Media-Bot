# JagoVideo Clone

Telegram bot for AI video/image generation, built with Python, `python-telegram-bot`, SQLite, and fal.ai. Runs in **polling mode** on Replit — no Vercel or Supabase required.

## How to run

```bash
uv run bot.py
```

The workflow **JagoVideo Clone Bot** is already configured for this command.

## Required secrets

Add these via **Tools → Secrets** before starting:

| Secret | Where to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) on Telegram |
| `FAL_KEY` | [fal.ai dashboard → Keys](https://fal.ai/dashboard/keys) |

The bot will print a clear error at startup if either key is missing.

## Optional settings

| Variable | Default | Description |
|---|---|---|
| `DATABASE_PATH` | `data/jagovideo.sqlite3` | SQLite database path |
| `ADMIN_USER_IDS` | *(empty)* | Comma-separated Telegram user IDs with admin commands |
| `ADMIN_CHAT_ID` | *(empty)* | Telegram chat ID that receives receipt notifications |
| `BOT_NAME` | `JagoVideo Clone` | Display name shown in the bot |
| `CHECKIN_BONUS` | `50` | Credits awarded for weekly check-in (sen) |
| `REFERRAL_BONUS` | `100` | Credits awarded per referral (sen) |

## Stack

- **Runtime**: Python 3.11+, managed by `uv`
- **Bot framework**: `python-telegram-bot` 21+
- **AI provider**: fal.ai (`fal-client`) — polling mode, no webhook needed
- **Database**: SQLite (`data/jagovideo.sqlite3`) — created automatically on first run
- **Handlers**: `bot/handlers.py` — stateless, all state persisted in SQLite

## Architecture

```
bot.py                    # Entry point — polling Application setup
bot/
  handlers.py             # All command/callback/message handlers
  keyboards.py            # InlineKeyboardMarkup builders
  states.py               # Conversation step constants
db/
  sqlite_db.py            # Connection, schema init (init_db())
  queries.py              # All DB operations — same interface as original Supabase version
services/
  fal_service.py          # fal.ai submit + poll (no webhook)
  credit_service.py       # Debit/refund helpers over db.queries
models_config.py          # AI model catalog (Veo, Kling, Seedance, FLUX, Nano Banana)
data/
  jagovideo.sqlite3       # SQLite database (auto-created on startup)
```

## Generation flow

1. User picks model → ratio → uploads image (if needed) → types prompt → confirms
2. Bot debits credits, submits job to fal.ai, stores `fal_request_id` in DB
3. A background `asyncio.create_task` polls the fal.ai handle
4. When done: bot sends `send_video` or `send_photo` directly to the user
5. On failure: credits are automatically refunded

## Admin commands

| Command | Description |
|---|---|
| `/addcredit USER_ID AMOUNT_SEN` | Manually add credits to a user |
| `/stats` | Total users, jobs, revenue |
| `/broadcast MESSAGE` | Send a message to all users |

## Credit system

All amounts are **integer sen** (RM 1.00 = 100 sen). Balance mutations use `BEGIN IMMEDIATE` SQLite transactions for atomicity.

## Payment top-up

The receipt upload flow (user sends screenshot → admin reviews) is fully wired. To enable it:
1. Add credit packages via direct SQL: `INSERT INTO credit_packages (name, price_rm, bonus_percent, credits_sen, is_active) VALUES (...)`
2. Optionally add payment instructions: `INSERT INTO payment_settings (id, payment_instructions, qr_image_url, payment_expiry_minutes) VALUES (1, '...', '...', 30)`
3. Set `ADMIN_CHAT_ID` so receipt notifications are forwarded to you

## User preferences
