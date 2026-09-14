"""Dispatcher wiring and bot profile (commands, descriptions)."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.base import BaseStorage
from aiogram.types import BotCommand
from sqlalchemy.ext.asyncio import async_sessionmaker

from flowpost.bot.handlers import (
    admin,
    billing,
    channel_admins,
    channel_settings,
    channels,
    content_plan,
    create_post,
    discussion,
    edit_post,
    menu,
    projects,
    settings as settings_handlers,
    start,
)
from flowpost.bot.handlers.editor import (
    ai,
    buttons,
    content,
    media,
    more,
    multipost,
    parts,
    publish,
    repeat,
    schedule,
    settings_menus,
)
from flowpost.bot.middlewares.access import AccessMiddleware
from flowpost.bot.middlewares.album import AlbumMiddleware
from flowpost.bot.middlewares.db import DbSessionMiddleware
from flowpost.bot.middlewares.user import UserMiddleware
from flowpost.config import Settings
from flowpost.i18n import LANGS, t

log = logging.getLogger(__name__)

COMMANDS = ["start", "newpost", "addchannel", "plan", "ad", "edit", "projects", "settings", "subscribe", "paysupport", "terms", "help"]


def build_dispatcher(settings: Settings, sessionmaker: async_sessionmaker, storage: BaseStorage) -> Dispatcher:
    dp = Dispatcher(storage=storage)
    # Private chats for all the bot's own flows, plus group/supergroup so `discussion.router`
    # can watch a linked discussion group for its auto-forwarded channel posts.
    dp.message.filter(F.chat.type.in_({"private", "group", "supergroup"}))

    dp.update.outer_middleware(DbSessionMiddleware(sessionmaker))
    dp.update.outer_middleware(UserMiddleware(settings))
    dp.message.outer_middleware(AlbumMiddleware())
    dp.message.middleware(AccessMiddleware())
    dp.callback_query.middleware(AccessMiddleware())

    # Order matters: menu buttons and commands first, state-specific inputs later,
    # and the "send content to start a post" catch-all last.
    dp.include_routers(
        admin.router,
        billing.router,
        start.router,
        discussion.router,
        channels.router,
        menu.router,
        content_plan.router,
        edit_post.router,
        projects.router,
        settings_handlers.router,
        channel_settings.router,
        channel_admins.router,
        content.router,
        buttons.router,
        media.router,
        settings_menus.router,
        ai.router,
        more.router,
        parts.router,
        repeat.router,
        schedule.router,
        multipost.router,
        publish.router,
        create_post.router,
    )
    return dp


async def setup_bot_profile(bot: Bot) -> None:
    """Menu button commands and the «Що вміє цей бот?» description, per language."""
    for lang in LANGS:
        language_code = None if lang == "en" else lang
        commands = [BotCommand(command=c, description=t(f"cmd.{c}", locale=lang)) for c in COMMANDS]
        try:
            await bot.set_my_commands(commands, language_code=language_code)
            await bot.set_my_description(t("bot.description", locale=lang), language_code=language_code)
            await bot.set_my_short_description(t("bot.short_description", locale=lang), language_code=language_code)
        except TelegramAPIError as e:
            log.warning("bot profile setup (%s) failed: %s", lang, e)
    # Russian-language clients in Ukraine get the Ukrainian interface texts too.
    try:
        await bot.set_my_commands(
            [BotCommand(command=c, description=t(f"cmd.{c}", locale="uk")) for c in COMMANDS], language_code="ru"
        )
    except TelegramAPIError as e:
        log.warning("bot commands (ru) failed: %s", e)
