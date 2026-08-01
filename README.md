# JagoVideo Clone

Telegram bot AI video/image generation service — deployed on **Vercel** (serverless Python) with **Supabase** as the database.

## Architecture

```
api/
  telegram-webhook.py   # POST — receives Telegram updates
  fal-webhook.py         # POST — receives fal.ai job completions
  health.py              # GET  — uptime ping
bot/
  handlers.py            # All command/conversation logic (stateless)
  keyboards.py           # InlineKeyboardMarkup builders
  states.py              # Conversation step constants
db/
  supabase_client.py     # Supabase client singleton
  queries.py             # All DB operations (read/write/RPC)
services/
  fal_service.py         # fal.ai job submission + URL extraction
  credit_service.py      # Balance debit/refund helpers
models_config.py          # AI model catalog (Veo, Kling, Seedance, FLUX, Nano Banana)
supabase_schema.sql       # Run once in Supabase SQL editor to create tables & RPCs
setup_webhook.py          # Run once locally to register the Telegram webhook
```

> **Stateless design**: conversation state (selected model, ratio, prompt) is stored in the `conversation_state` table in Supabase, not in Python memory. Each Vercel invocation reads and writes that row.

## Quick start

### 1. Set up Supabase

1. Create a project at [supabase.com](https://supabase.com).
2. Open the SQL editor and run the entire contents of `supabase_schema.sql`.
3. Copy the **Project URL** and **service_role** key (Settings → API).

### 2. Set up fal.ai

1. Create an account at [fal.ai](https://fal.ai).
2. Go to your dashboard and generate an API key.

### 3. Deploy to Vercel

```bash
# Install Vercel CLI (once)
npm i -g vercel

# Deploy (first time — follow prompts)
vercel

# Set environment variables
vercel env add TELEGRAM_BOT_TOKEN
vercel env add FAL_KEY
vercel env add SUPABASE_URL
vercel env add SUPABASE_SERVICE_ROLE_KEY
vercel env add ADMIN_CHAT_ID       # optional — your Telegram chat ID for receipt alerts
vercel env add ADMIN_USER_IDS      # optional — comma-separated IDs with admin commands
vercel env add VERCEL_DOMAIN       # e.g. https://yourbot.vercel.app

# Redeploy with env vars
vercel --prod
```

### 4. Register the Telegram webhook

```bash
TELEGRAM_BOT_TOKEN=... VERCEL_DOMAIN=https://yourbot.vercel.app python setup_webhook.py
```

You only need to do this once (or after changing the domain).

## Environment variables

| Variable                  | Required | Description |
|---------------------------|----------|-------------|
| `TELEGRAM_BOT_TOKEN`      | ✅        | From [@BotFather](https://t.me/BotFather) |
| `FAL_KEY`                 | ✅        | From [fal.ai](https://fal.ai) dashboard |
| `SUPABASE_URL`            | ✅        | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅      | Supabase service_role key (never expose publicly) |
| `VERCEL_DOMAIN`           | ✅        | Your Vercel deployment URL (for fal.ai webhook callback) |
| `ADMIN_USER_IDS`          | optional | Comma-separated Telegram user IDs for admin commands |
| `ADMIN_CHAT_ID`           | optional | Telegram chat ID that receives receipt notifications |
| `BOT_NAME`                | optional | Display name (default: `JagoVideo Clone`) |
| `CHECKIN_BONUS`           | optional | Weekly check-in bonus in sen (default: `50`) |
| `REFERRAL_BONUS`          | optional | Referral bonus in sen (default: `100`) |

## Admin commands

| Command | Description |
|---------|-------------|
| `/addcredit USER_ID AMOUNT_SEN` | Manually add credits to a user |
| `/stats` | Show total users, jobs, and revenue |
| `/broadcast MESSAGE` | Send a message to all users |

## Credit system

All amounts are stored as integer **sen** (1 RM = 100 sen).  
Atomic balance mutations are handled by Supabase RPCs (`deduct_credit` / `add_credit`).

## Available models

| Model | Type | Price |
|-------|------|-------|
| Veo (text-to-video) | Video | per job |
| Kling (image-to-video) | Video | per job |
| Seedance (optional image) | Video | per job |
| FLUX (text-to-image) | Image | per job |
| Nano Banana (image optional) | Image | per job |

See `models_config.py` for endpoint, pricing, and ratio details.
