from __future__ import annotations

import logging

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import Settings, load_settings
from database import Database
from handlers.admin import admin_handlers
from handlers.balance import show_balance
from handlers.common import get_services
from handlers.credit import choose_credit, show_credit
from handlers.history import history_page, show_history
from handlers.image_generation import image_conversation
from handlers.referral import show_referral
from handlers.settings import feedback, language, leaderboard, weekly_checkin
from handlers.start import back_to_menu, start
from handlers.video_generation import video_conversation
from services.credit_service import CreditService
from services.fal_service import FalService
from services.generation_service import GenerationService
from services.payment_service import PaymentService

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("jagovideo")


async def post_init(application: Application) -> None:
    db: Database = application.bot_data["db"]
    await db.connect()
    me = await application.bot.get_me()
    logger.info("JagoVideo Clone started as @%s", me.username)


async def post_shutdown(application: Application) -> None:
    await application.bot_data["db"].close()


def build_application(settings: Settings) -> Application:
    db = Database(settings.database_path)
    fal = FalService(settings.fal_key)
    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.bot_data.update(
        settings=settings,
        db=db,
        fal=fal,
        credit=CreditService(db),
        generation=GenerationService(db, fal),
        payment=PaymentService(db, settings.payment_gateway_key),
    )

    # ── Commands ──────────────────────────────────────────────────────────────
    application.add_handler(CommandHandler("start", start))

    # ── Generation conversations (entry via menu:video / menu:image callbacks) ─
    application.add_handler(video_conversation)
    application.add_handler(image_conversation)

    # ── Main-menu navigation ──────────────────────────────────────────────────
    application.add_handler(CallbackQueryHandler(back_to_menu,    pattern=r"^menu:back$"))
    application.add_handler(CallbackQueryHandler(show_credit,     pattern=r"^menu:credit$"))
    application.add_handler(CallbackQueryHandler(show_balance,    pattern=r"^menu:balance$"))
    application.add_handler(CallbackQueryHandler(show_referral,   pattern=r"^menu:referral$"))
    application.add_handler(CallbackQueryHandler(show_history,    pattern=r"^menu:history$"))
    application.add_handler(CallbackQueryHandler(feedback,        pattern=r"^menu:feedback$"))
    application.add_handler(CallbackQueryHandler(language,        pattern=r"^menu:language$"))
    application.add_handler(CallbackQueryHandler(weekly_checkin,  pattern=r"^menu:checkin$"))
    application.add_handler(CallbackQueryHandler(leaderboard,     pattern=r"^menu:leaderboard$"))

    # ── Sub-flow callbacks ────────────────────────────────────────────────────
    application.add_handler(CallbackQueryHandler(choose_credit, pattern=r"^credit:"))
    application.add_handler(CallbackQueryHandler(history_page,  pattern=r"^history:"))

    # ── Admin commands ────────────────────────────────────────────────────────
    for handler in admin_handlers():
        application.add_handler(handler)

    return application


def main() -> None:
    settings = load_settings()
    application = build_application(settings)
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
