"""Run this script once manually after deploying to Vercel to register the webhook.

Usage:
    TELEGRAM_BOT_TOKEN=... VERCEL_DOMAIN=https://yourbot.vercel.app python setup_webhook.py
"""

import os
import requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
VERCEL_URL = os.environ.get("VERCEL_DOMAIN")  # e.g. https://namabot.vercel.app

if not BOT_TOKEN or not VERCEL_URL:
    raise SystemExit("TELEGRAM_BOT_TOKEN and VERCEL_DOMAIN must be set.")

webhook_url = f"{VERCEL_URL}/api/telegram-webhook"
response = requests.post(
    f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
    json={"url": webhook_url, "allowed_updates": ["message", "callback_query"]},
)
print(response.json())
