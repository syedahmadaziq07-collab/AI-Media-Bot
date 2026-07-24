# JagoVideo Clone

Telegram bot AI video/image generation service built with Python,
`python-telegram-bot`, SQLite, and fal.ai.

## Run

```bash
uv run bot.py
```

Required secrets:

- `TELEGRAM_BOT_TOKEN`
- `FAL_KEY`

Optional settings are documented in `.env.example`. Credit amounts are stored
as integer sen. The payment gateway is intentionally isolated behind
`services/payment_service.py`; use `/addcredit USER_ID JUMLAH_SEN` for local
admin testing until a gateway webhook is connected.

## Safety rules

- Generation credit is debited atomically before provider submission.
- Failed jobs are automatically refunded.
- fal.ai polling runs in an asyncio task and does not block Telegram updates.
- Uploaded images are restricted to JPG/PNG and 10MB.