"""Entry point: `python -m flowpost`."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from flowpost.bot.setup import build_dispatcher, setup_bot_profile
from flowpost.config import Settings, get_settings
from flowpost.db.session import create_engine, create_sessionmaker
from flowpost.services.ai import AIService
from flowpost.services.publisher import Publisher
from flowpost.services.watermark import Watermarker
from flowpost.services.worker import Worker
from flowpost.web import build_web_app

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("flowpost")


def run_migrations(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["configure_logger"] = False  # keep our logging setup
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(cfg, "head")


def make_storage(settings: Settings) -> BaseStorage:
    if settings.redis_url:
        from aiogram.fsm.storage.redis import RedisStorage

        return RedisStorage.from_url(settings.redis_url)
    return MemoryStorage()


async def run(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    sessionmaker = create_sessionmaker(engine)
    bot = Bot(settings.bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    publisher = Publisher(bot, Watermarker(settings.ffmpeg_bin, settings.watermark_font, settings.watermark_concurrency))
    worker = Worker(bot, sessionmaker, publisher, settings)
    dp = build_dispatcher(settings, sessionmaker, make_storage(settings))
    dp.workflow_data.update(settings=settings, publisher=publisher, worker=worker, ai=AIService(settings))

    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError:
        log.error("Telegram rejected BOT_TOKEN — copy the token from @BotFather into .env")
        await bot.session.close()
        await engine.dispose()
        raise SystemExit(1)
    log.info("Starting as @%s", me.username)
    await setup_bot_profile(bot)
    app = build_web_app(settings, bot, sessionmaker)
    webhook_url = settings.webhook_url
    if webhook_url:
        SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=settings.webhook_secret or None).register(
            app, path="/tg/webhook"
        )
        setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, settings.web_host, settings.web_port).start()
    log.info("HTTP server on %s:%s", settings.web_host, settings.web_port)
    worker_task = asyncio.create_task(worker.run(), name="flowpost-worker")
    try:
        if webhook_url:
            await bot.set_webhook(
                webhook_url,
                secret_token=settings.webhook_secret or None,
                allowed_updates=dp.resolve_used_update_types(),
            )
            log.info("Webhook mode: %s", webhook_url)
            await asyncio.Event().wait()
        else:
            await bot.delete_webhook()
            log.info("Polling mode")
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        worker_task.cancel()
        await runner.cleanup()
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)
    settings = get_settings()
    run_migrations(settings.database_url)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
