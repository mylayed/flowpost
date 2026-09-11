from __future__ import annotations

import html
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.keyboards.common import add_channel_inline_kb
from flowpost.bot.keyboards.main_menu import main_menu_kb
from flowpost.config import Settings
from flowpost.db.models import User
from flowpost.db.repo import channels as channels_repo
from flowpost.i18n import t, variants

ASSETS = Path(__file__).resolve().parents[3] / "assets"
router = Router(name="start")


async def send_main_menu(message: Message, text: str | None = None) -> None:
    await message.answer(text or t("menu.main"), reply_markup=main_menu_kb())


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, user: User, session: AsyncSession, settings: Settings) -> None:
    await state.clear()
    name = html.escape(message.from_user.first_name if message.from_user else "")
    text = t("start.welcome", name=name, days=settings.trial_days)
    image = ASSETS / "start.png"
    if image.exists():
        await message.answer_photo(FSInputFile(image), caption=text, reply_markup=main_menu_kb())
    else:
        await message.answer(text, reply_markup=main_menu_kb())
    if not await channels_repo.list_channels(session, user.id):
        await message.answer(t("start.no_channels"), reply_markup=add_channel_inline_kb())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(t("help.text"))


@router.message(Command("menu"))
@router.message(F.text.in_(variants("btn.main_menu")))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_main_menu(message)
