from __future__ import annotations

import html
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.keyboards.common import add_channel_inline_kb
from flowpost.bot.keyboards.main_menu import main_menu_kb
from flowpost.config import Settings
from flowpost.db.models import Channel, User
from flowpost.db.repo import channel_admins as channel_admins_repo
from flowpost.db.repo import channels as channels_repo
from flowpost.i18n import t, variants

ASSETS = Path(__file__).resolve().parents[3] / "assets"
router = Router(name="start")


async def send_main_menu(message: Message, text: str | None = None) -> None:
    await message.answer(text or t("menu.main"), reply_markup=main_menu_kb())


async def _redeem_admin_invite(message: Message, session: AsyncSession, user: User, token: str) -> None:
    # Row-locked so two concurrent redemptions of the same link can't both pass the used_by check.
    invite = await channel_admins_repo.get_invite(session, token, for_update=True)
    channel = await session.get(Channel, invite.channel_id) if invite else None
    if invite is None or invite.revoked or invite.used_by is not None or channel is None or not channel.is_active:
        await message.answer(t("admins.invite_invalid"), reply_markup=main_menu_kb())
        return
    if channel.owner_id == user.id:
        await message.answer(t("admins.invite_self"), reply_markup=main_menu_kb())
        return
    await channel_admins_repo.redeem_invite(session, invite, user.id)
    perms = ", ".join(
        t(f"admins.perm_{p}") for p in channel_admins_repo.invite_permissions_label(invite)
    )
    await message.answer(
        t("admins.invite_accepted", title=html.escape(channel.title), perms=perms), reply_markup=main_menu_kb()
    )


@router.message(CommandStart())
async def cmd_start(
    message: Message, command: CommandObject, state: FSMContext, user: User, session: AsyncSession, settings: Settings,
) -> None:
    await state.clear()
    if command.args and command.args.startswith("adm_"):
        await _redeem_admin_invite(message, session, user, command.args[len("adm_"):])
        return
    name = html.escape(message.from_user.first_name if message.from_user else "")
    text = t("start.welcome", name=name, days=settings.trial_days)
    image = ASSETS / "start.png"
    if image.exists():
        await message.answer_photo(FSInputFile(image), caption=text, reply_markup=main_menu_kb())
    else:
        await message.answer(text, reply_markup=main_menu_kb())
    if not await channels_repo.list_channels(session, user.id, perm="posts"):
        await message.answer(t("start.no_channels"), reply_markup=add_channel_inline_kb())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(t("help.text"))


@router.message(Command("menu"))
@router.message(F.text.in_(variants("btn.main_menu")))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_main_menu(message)
