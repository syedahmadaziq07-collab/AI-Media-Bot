# JagoVideo Clone

Telegram bot for credit-based AI video and image generation through fal.ai.

## Run & Operate

- `uv run bot.py` — run the Telegram bot
- `python -m compileall bot.py config.py database handlers services models_config.py` — check Python syntax
- Required secrets: `TELEGRAM_BOT_TOKEN`, `FAL_KEY`
- Optional: `ADMIN_USER_IDS`, `PAYMENT_GATEWAY_KEY`, `DATABASE_PATH`

## Stack

- Python 3.11+
- Telegram: python-telegram-bot 21+
- Provider: fal-client
- Database: SQLite via aiosqlite

## Where things live

- `bot.py` — application setup and handler registration
- `database/` — SQLite migrations and atomic balance ledger
- `handlers/` — Telegram flows
- `services/` — credits, payments, fal.ai, and generation worker
- `models_config.py` — model catalog and pricing

## Architecture decisions

- Balances are integer sen and are changed inside an immediate SQLite transaction.
- Credit is debited before fal.ai submission and refunded on failure.
- Provider polling is isolated in asyncio tasks so the bot event loop remains responsive.
- Payment provider wiring is isolated until a gateway is selected and authorized.

## Product

Users can generate AI video/image jobs, manage credit, view history, earn referral
and weekly check-in bonuses, and see a leaderboard from Telegram.

## User preferences

Keep user-facing bot copy in Bahasa Melayu.

## Gotchas

- Verify fal.ai model endpoint schemas and wholesale pricing before production.
- Add `ADMIN_USER_IDS` before using admin commands.
- Connect a payment gateway before exposing real top-up checkout.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
