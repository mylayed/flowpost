"""/addchannel: connecting channels and groups, tracking the bot's admin status."""
from __future__ import annotations

import html
import logging
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChatMemberUpdated, FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Cs, Pj
from flowpost.bot.handlers.start import ASSETS
from flowpost.bot.keyboards.common import btn, markup
from flowpost.bot.keyboards.main_menu import REQUEST_CHANNEL, add_channel_kb, main_menu_kb
from flowpost.config import Settings
from flowpost.db.models import User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import users as users_repo
from flowpost.i18n import t
from flowpost.services import analytics

log = logging.getLogger(__name__)
router = Router(name="channels")

# chat_shared and my_chat_member arrive together when connecting via the chat picker; notify once.
_recent_connects: dict[tuple[int, int], float] = {}


def _first_notice(user_id: int, chat_id: int) -> bool:
    now = time.monotonic()
    for key, ts in list(_recent_connects.items()):
        if now - ts > 120:
            _recent_connects.pop(key, None)
    if (user_id, chat_id) in _recent_connects:
        return False
    _recent_connects[(user_id, chat_id)] = now
    return True


async def send_add_channel_screen(message: Message) -> None:
    text = t("addch.text")
    image = ASSETS / "addchannel.png"
    if image.exists():
        await message.answer_photo(FSInputFile(image), caption=text, reply_markup=add_channel_kb())
    else:
        await message.answer(text, reply_markup=add_channel_kb())


@router.message(Command("addchannel"))
async def cmd_addchannel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_add_channel_screen(message)


@router.callback_query(Pj.filter(F.a == "add"))
async def cb_addchannel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.answer()
    if cb.message:
        await send_add_channel_screen(cb.message)


def rights_error(kind: str, bot_member, user_member) -> str | None:
    if str(user_member.status) not in ("creator", "administrator"):
        return "addch.err_user_not_admin"
    if str(bot_member.status) != "administrator":
        return "addch.err_bot_not_admin"
    if kind == "channel" and not getattr(bot_member, "can_post_messages", False):
        return "addch.err_no_post_right"
    return None


async def after_connected(message: Message, channel, *, notify: bool) -> None:
    if notify:
        await message.answer(t("addch.done", title=html.escape(channel.title)), reply_markup=main_menu_kb())
    if channel.is_forum and channel.topic_id is None:
        await message.answer(
            t("addch.forum"),
            reply_markup=markup([[
                btn(t("btn.topic_general"), Cs(a="topic_general", c=channel.id)),
                btn(t("btn.topic_set"), Cs(a="topic", c=channel.id)),
            ]]),
        )


@router.message(F.chat_shared)
async def on_chat_shared(message: Message, bot: Bot, session: AsyncSession, user: User, settings: Settings) -> None:
    shared = message.chat_shared
    kind = "channel" if shared.request_id == REQUEST_CHANNEL else "group"
    try:
        me = await bot.me()
        bot_member = await bot.get_chat_member(shared.chat_id, me.id)
        user_member = await bot.get_chat_member(shared.chat_id, user.tg_id)
        chat = await bot.get_chat(shared.chat_id)
    except TelegramAPIError as e:
        log.info("chat_shared check failed: %s", e)
        await message.answer(t("addch.err_no_access"), reply_markup=add_channel_kb())
        return
    error = rights_error(kind, bot_member, user_member)
    if error:
        await message.answer(t(error), reply_markup=add_channel_kb())
        return
    channel, _created = await channels_repo.upsert_channel(
        session,
        user.id,
        chat_id=chat.id,
        kind="channel" if chat.type == "channel" else "group",
        title=chat.title or "",
        username=chat.username,
        is_forum=bool(chat.is_forum),
        trial_days=settings.trial_days,
    )
    analytics.track(session, user.id, "channel_connected", chat_id=chat.id)
    notify = _first_notice(user.id, chat.id)
    if not notify:
        await message.answer(t("menu.main"), reply_markup=main_menu_kb())
    await after_connected(message, channel, notify=notify)


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated, bot: Bot, session: AsyncSession, settings: Settings) -> None:
    chat = event.chat
    new = event.new_chat_member
    status = str(new.status)

    if chat.type == "private":
        db_user = await users_repo.get_by_tg(session, chat.id)
        if db_user is not None:
            db_user.is_blocked = status == "kicked"
        return

    if await channels_repo.is_discussion_group(session, chat.id):
        # This chat is designated as a comments group for some channel — never (re)register it
        # as its own postable project, no matter what admin-status change Telegram just sent.
        return

    kind = "channel" if chat.type == "channel" else "group"
    has_rights = status == "administrator" and (kind != "channel" or bool(getattr(new, "can_post_messages", False)))

    if not has_rights:
        for channel in await channels_repo.channels_by_chat(session, chat.id):
            if not channel.is_active:
                continue
            channel.is_active = False
            owner = await session.get(User, channel.owner_id)
            if owner is None or owner.is_blocked:
                continue
            try:
                await bot.send_message(owner.tg_id, t("addch.lost", locale=owner.lang, title=html.escape(channel.title)))
            except TelegramAPIError:
                pass
        return

    if event.from_user is None or event.from_user.is_bot:
        return
    adder = await users_repo.get_by_tg(session, event.from_user.id)
    if adder is None:
        return
    channel, _created = await channels_repo.upsert_channel(
        session,
        adder.id,
        chat_id=chat.id,
        kind=kind,
        title=chat.title or "",
        username=chat.username,
        is_forum=bool(getattr(chat, "is_forum", False)),
        trial_days=settings.trial_days,
    )
    if _first_notice(adder.id, chat.id):
        try:
            await bot.send_message(
                adder.tg_id, t("addch.done", locale=adder.lang, title=html.escape(channel.title))
            )
        except TelegramAPIError:
            pass
