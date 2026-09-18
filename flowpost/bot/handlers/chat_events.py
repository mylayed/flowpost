"""Updates from connected channels: join requests, people joining or leaving, and «show hidden text» taps."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, ChatJoinRequest, ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.config import Settings
from flowpost.db.models import Post, User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.types import utcnow
from flowpost.i18n import detect_lang, t
from flowpost.services import growth
from flowpost.services.billing import entitlements
from flowpost.services.posts import HIDDEN_PREFIX, options_of

log = logging.getLogger(__name__)
router = Router(name="chat_events")

IN_CHAT = {"member", "administrator", "creator"}


def _is_in(member) -> bool:
    status = str(getattr(member, "status", ""))
    return status in IN_CHAT or (status == "restricted" and bool(getattr(member, "is_member", False)))


@router.chat_join_request()
async def on_join_request(request: ChatJoinRequest, bot: Bot, session: AsyncSession, settings: Settings) -> None:
    channel = next(
        (c for c in await channels_repo.channels_by_chat(session, request.chat.id) if c.is_active and growth.handles_requests(c)),
        None,
    )
    if channel is None:
        return
    now = utcnow()
    owner = await session.get(User, channel.owner_id)
    if owner is None or not entitlements.has_extras(await entitlements.for_channel(session, settings, channel, owner, now)):
        return
    url = request.invite_link.invite_link if request.invite_link else None
    row = await growth.queue_request(session, channel, request.from_user.id, url, now)
    if growth.join_settings(channel.join_settings)["welcome"]:
        lang = detect_lang(request.from_user.language_code)
        try:
            # Telegram lets the bot write to someone who asked to join, via user_chat_id, for a short while.
            await bot.send_message(request.user_chat_id, growth.welcome_text(channel, request.from_user.first_name, lang))
        except TelegramAPIError as e:
            log.info("welcome to %s not delivered: %s", request.from_user.id, e)
    if row.approve_at is not None and row.approve_at <= now:
        await growth.approve_request(bot, session, channel, row, now)


@router.chat_member()
async def on_member_change(update: ChatMemberUpdated, session: AsyncSession) -> None:
    was_in, is_in = _is_in(update.old_chat_member), _is_in(update.new_chat_member)
    user_id = update.new_chat_member.user.id
    now = utcnow()
    if not was_in and is_in:
        link = await growth.find_link(session, update.chat.id, update.invite_link.invite_link if update.invite_link else None)
        if link is not None:
            await growth.record_join(session, link, user_id, now)
    elif was_in and not is_in:
        await growth.record_leave(session, update.chat.id, user_id, now)


@router.callback_query(F.data.startswith(HIDDEN_PREFIX))
async def on_hidden_text(cb: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    lang = detect_lang(cb.from_user.language_code)
    raw = (cb.data or "")[len(HIDDEN_PREFIX):]
    post = await session.get(Post, int(raw)) if raw.isdigit() else None
    text = options_of(post).get("hidden_text") if post is not None else None
    if not text:
        await cb.answer(t("hidden.gone", locale=lang), show_alert=True)
        return
    chat = cb.message.chat if cb.message is not None else None
    if chat is not None and chat.type != "private":
        try:
            member = await bot.get_chat_member(chat.id, cb.from_user.id)
        except TelegramAPIError as e:
            log.info("membership check in %s failed: %s", chat.id, e)
            member = None
        if not _is_in(member):
            await cb.answer(t("hidden.subscribe", locale=lang), show_alert=True)
            return
    await cb.answer(text, show_alert=True)
