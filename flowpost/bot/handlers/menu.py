"""Main reply-keyboard buttons and their slash-command twins. Registered before any state handlers."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.handlers import content_plan, edit_post, projects, settings as settings_handlers
from flowpost.bot.handlers.create_post import start_post
from flowpost.config import Settings
from flowpost.db.models import User
from flowpost.i18n import variants
from flowpost.services.publisher import Publisher

router = Router(name="menu")


@router.message(Command("newpost"))
@router.message(F.text.in_(variants("btn.create_post")))
async def menu_create_post(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher
) -> None:
    await start_post(message, bot, session, state, user, publisher)


@router.message(Command("ad"))
@router.message(F.text.in_(variants("btn.ad_post")))
async def menu_ad_post(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher
) -> None:
    await start_post(message, bot, session, state, user, publisher, is_ad=True)


@router.message(Command("plan"))
@router.message(F.text.in_(variants("btn.content_plan")))
async def menu_content_plan(message: Message, session: AsyncSession, state: FSMContext, user: User) -> None:
    await state.clear()
    await content_plan.send_plan(message, session, user)


@router.message(Command("edit"))
@router.message(F.text.in_(variants("btn.edit_post")))
async def menu_edit_post(message: Message, session: AsyncSession, state: FSMContext, user: User) -> None:
    await edit_post.send_list(message, session, state, user)


@router.message(Command("projects"))
@router.message(F.text.in_(variants("btn.projects")))
async def menu_projects(message: Message, session: AsyncSession, state: FSMContext, user: User) -> None:
    await state.clear()
    await projects.send_projects(message, session, user)


@router.message(Command("settings"))
@router.message(F.text.in_(variants("btn.settings")))
async def menu_settings(
    message: Message, session: AsyncSession, state: FSMContext, user: User, settings: Settings
) -> None:
    await state.clear()
    await settings_handlers.send_settings(message, session, user, settings)
