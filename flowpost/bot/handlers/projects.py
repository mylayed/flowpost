"""«Мої проєкти»: connected channels/groups and their settings."""
from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Pj
from flowpost.bot.handlers.channel_settings import channel_card
from flowpost.bot.keyboards.common import btn, markup
from flowpost.db.models import Publication, User
from flowpost.db.repo import channels as channels_repo
from flowpost.i18n import t

router = Router(name="projects")


async def projects_view(session: AsyncSession, user: User) -> tuple[str, InlineKeyboardMarkup]:
    channels = await channels_repo.list_channels(session, user.id, active_only=False)
    rows = [
        [btn(
            ("📢 " if c.kind == "channel" else "👥 ") + c.title + (" 🔊" if c.notify_published else " 🔇"),
            Pj(a="ch", c=c.id),
        )]
        for c in channels
    ]
    rows.append([btn(t("btn.add_channel"), Pj(a="add"))])
    text = t("proj.title") + "\n\n" + (t("proj.help") if channels else t("proj.empty"))
    return text, markup(rows)


async def send_projects(message: Message, session: AsyncSession, user: User) -> None:
    text, kb = await projects_view(session, user)
    await message.answer(text, reply_markup=kb)


async def _edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None) -> None:
    if cb.message is None:
        return
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await cb.message.answer(text, reply_markup=kb)


@router.callback_query(Pj.filter(F.a == "list"))
async def pj_list(cb: CallbackQuery, session: AsyncSession, user: User) -> None:
    await cb.answer()
    await _edit(cb, *await projects_view(session, user))


@router.callback_query(Pj.filter(F.a == "ch"))
async def pj_channel(cb: CallbackQuery, callback_data: Pj, session: AsyncSession, user: User) -> None:
    channel = await channels_repo.get_channel(session, user.id, callback_data.c)
    if channel is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    await cb.answer()
    await _edit(cb, *channel_card(channel))


@router.callback_query(Pj.filter(F.a.in_({"off", "offok"})))
async def pj_disconnect(cb: CallbackQuery, callback_data: Pj, session: AsyncSession, user: User) -> None:
    channel = await channels_repo.get_channel(session, user.id, callback_data.c)
    if channel is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    if callback_data.a == "off":
        await cb.answer()
        kb = markup([
            [btn(t("proj.disconnect_yes"), Pj(a="offok", c=channel.id))],
            [btn(t("btn.back"), Pj(a="ch", c=channel.id))],
        ])
        await _edit(cb, t("proj.disconnect_confirm", title=html.escape(channel.title)), kb)
        return
    channel.is_active = False
    await session.execute(
        update(Publication)
        .where(Publication.channel_id == channel.id, Publication.status.in_(("pending", "paused")))
        .values(status="cancelled")
    )
    await session.flush()
    await cb.answer(t("proj.disconnected"))
    await _edit(cb, *await projects_view(session, user))
