"""Linking a channel's discussion group and closing its topic when comments are turned off for a post."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import ChatShared, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.handlers.channel_settings import cm_menu
from flowpost.bot.keyboards.main_menu import REQUEST_DISCUSSION, main_menu_kb
from flowpost.bot.states import ChannelInput
from flowpost.db.models import Channel, Publication, User
from flowpost.db.repo import channel_admins as channel_admins_repo
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.i18n import t
from flowpost.services.delivery import publication_message_ids
from flowpost.services.moderation import moderation_settings, violation
from flowpost.services.posts import options_of

log = logging.getLogger(__name__)
router = Router(name="discussion")
_flood_cache: dict[tuple[int, int, int], tuple[str, float]] = {}
_FLOOD_CACHE_MAX = 5000


@router.message(StateFilter(ChannelInput.discussion_group), F.chat_shared)
async def on_discussion_group_shared(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    shared: ChatShared = message.chat_shared
    data = await state.get_data()
    channel = await channels_repo.get_channel(session, user.id, int(data.get("cs_channel") or 0))
    await state.set_state(None)
    allowed = channel is not None and (
        channel.owner_id == user.id
        or await channel_admins_repo.has_permission(session, channel.id, user.id, "settings")
    )
    if not allowed:
        await message.answer(t("err.not_found"), reply_markup=main_menu_kb())
        return
    if shared.request_id != REQUEST_DISCUSSION:
        return
    try:
        me = await bot.me()
        bot_member = await bot.get_chat_member(shared.chat_id, me.id)
        chat = await bot.get_chat(shared.chat_id)
    except TelegramAPIError as e:
        log.info("discussion chat_shared check failed: %s", e)
        await message.answer(t("addch.err_no_access"), reply_markup=main_menu_kb())
        return
    if str(bot_member.status) != "administrator":
        await message.answer(t("cm.err_bot_not_admin"), reply_markup=main_menu_kb())
        return
    channel.discussion_chat_id = chat.id
    channel.discussion_title = chat.title or ""
    # This chat may already exist as its own postable project (e.g. the bot became its admin
    # before it was designated a comments group, or the group got a new chat_id by migrating
    # to a supergroup before we started tracking that) — it no longer belongs in that list.
    stale = await session.scalars(
        select(Channel).where(
            Channel.owner_id == user.id, Channel.kind == "group", Channel.chat_id != chat.id,
            (Channel.chat_id == shared.chat_id) | (Channel.title == (chat.title or "")),
        )
    )
    for project in [*await channels_repo.channels_by_chat(session, chat.id), *stale.all()]:
        if project.id != channel.id and project.owner_id == user.id:
            project.is_active = False
    await session.flush()
    await message.answer(t("cm.linked_done", title=chat.title or ""), reply_markup=main_menu_kb())
    text, kb = cm_menu(channel)
    await message.answer(text, reply_markup=kb)


@router.message(F.migrate_to_chat_id)
async def on_group_migrated(message: Message, session: AsyncSession) -> None:
    """A basic group becomes a supergroup (e.g. when Topics is turned on) and gets a new chat_id."""
    old_id, new_id = message.chat.id, message.migrate_to_chat_id
    for channel in await channels_repo.channels_by_chat(session, old_id):
        channel.chat_id = new_id
    for channel in (await session.scalars(select(Channel).where(Channel.discussion_chat_id == old_id))).all():
        channel.discussion_chat_id = new_id
    await session.flush()


@router.message(F.chat.type.in_({"group", "supergroup"}), F.is_automatic_forward, F.forward_origin)
async def on_channel_autopost(message: Message, bot: Bot, session: AsyncSession) -> None:
    origin = message.forward_origin
    if origin.type != "channel" or not message.is_topic_message or not message.message_thread_id:
        return
    channel = await session.scalar(
        select(Channel).where(Channel.discussion_chat_id == message.chat.id, Channel.chat_id == origin.chat.id)
    )
    if channel is None:
        return
    pubs = (
        await session.scalars(
            select(Publication)
            .where(Publication.channel_id == channel.id, Publication.status == "published")
            .order_by(Publication.id.desc())
            .limit(50)
        )
    ).all()
    pub = next((p for p in pubs if origin.message_id in publication_message_ids(p)), None)
    if pub is None:
        return
    pub.discussion_thread_id = message.message_thread_id
    post = await posts_repo.get_post(session, pub.owner_id, pub.post_id)
    if post is None or options_of(post).get("comments", True):
        return
    try:
        await bot.close_forum_topic(message.chat.id, message.message_thread_id)
    except TelegramAPIError as e:
        log.info("close_forum_topic failed for channel %s: %s", channel.id, e)


@router.message(
    F.chat.type.in_({"group", "supergroup"}), F.message_thread_id, ~F.is_automatic_forward,
)
async def on_discussion_comment(message: Message, bot: Bot, session: AsyncSession) -> None:
    """Moderate and count a reply in a linked discussion thread as a comment on the post that opened it."""
    if message.from_user is None or message.from_user.is_bot:
        return
    channel = await session.scalar(select(Channel).where(Channel.discussion_chat_id == message.chat.id))
    if channel is None:
        return
    mod = moderation_settings(channel.moderation)
    if mod["enabled"]:
        text = message.text or message.caption or ""
        thread_id = message.message_thread_id or 0
        if len(_flood_cache) > _FLOOD_CACHE_MAX:
            _flood_cache.clear()
        kind = violation(text, mod["banned_words"], _flood_cache, message.chat.id, thread_id, message.from_user.id)
        if kind is not None:
            try:
                await bot.delete_message(message.chat.id, message.message_id)
                log.info("moderation deleted %s message in chat %s", kind, message.chat.id)
            except TelegramAPIError as e:
                log.info("moderation delete failed in chat %s: %s", message.chat.id, e)
            return
    pub = await session.scalar(
        select(Publication).where(
            Publication.channel_id == channel.id,
            Publication.discussion_thread_id == message.message_thread_id,
            Publication.status == "published",
        )
    )
    if pub is None:
        return
    pub.comments_count = (pub.comments_count or 0) + 1
