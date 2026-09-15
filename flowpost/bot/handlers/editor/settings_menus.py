"""Editor → «Водяний знак» and «Автопідпис»: open channel-level menus in the panel."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.channel_settings import sig_menu, wm_menu
from flowpost.bot.handlers.editor.view import post_from_callback, show_panel
from flowpost.db.models import User
from flowpost.db.repo import channel_admins as channel_admins_repo
from flowpost.db.repo import channels as channels_repo
from flowpost.i18n import t

router = Router(name="editor_settings_menus")


@router.callback_query(Ed.filter(F.a.in_({"wm", "sig"})))
async def ed_channel_menu(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
    if not channels:
        await cb.answer(t("post.no_channels"), show_alert=True)
        return
    await cb.answer()
    channel = channels[0]
    can_settings = channel.owner_id == user.id or await channel_admins_repo.has_permission(
        session, channel.id, user.id, "settings"
    )
    builder = wm_menu if callback_data.a == "wm" else sig_menu
    text, kb = builder(channel, post, can_settings=can_settings)
    if len(channels) > 1:
        text += "\n\n" + t("ed.primary_channel_note")
    await show_panel(bot, cb.from_user.id, state, text, kb)
