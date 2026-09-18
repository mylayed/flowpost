"""«Підтримка» through a forum supergroup: one topic per user, the team answers inside it as the bot."""
from __future__ import annotations

import html
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Channel, SupportThread, User

log = logging.getLogger(__name__)

_TOPIC_GONE = ("THREAD NOT FOUND", "TOPIC_DELETED", "TOPIC_ID_INVALID")


def topic_name(user: User) -> str:
    name = user.first_name or str(user.tg_id)
    if user.username:
        name += f" @{user.username}"
    return f"{name} · {user.tg_id}"[:128]


async def _card(session: AsyncSession, user: User) -> str:
    """The first message of a user's topic: who they are, so the team doesn't have to look it up."""
    channels = await session.scalar(
        select(func.count()).select_from(Channel).where(Channel.owner_id == user.id, Channel.is_active)
    )
    who = html.escape(user.first_name or "—") + (f" @{html.escape(user.username)}" if user.username else "")
    return (
        f"🆘 <b>Звернення в підтримку</b>\n\n"
        f"👤 {who}\n"
        f"🆔 <code>{user.tg_id}</code>\n"
        f"🌐 {user.lang} · {html.escape(user.tz)}\n"
        f"📡 Каналів: {channels or 0}\n"
        f"📅 З нами з {user.created_at:%d.%m.%Y}\n\n"
        "Пишіть у цю тему — бот перешле відповідь користувачу від свого імені. "
        "Повідомлення, що починаються з «/», лишаються тут (нотатки для команди)."
    )


async def _thread(bot: Bot, session: AsyncSession, chat_id: int, user: User, *, fresh: bool = False) -> SupportThread:
    thread = await session.scalar(
        select(SupportThread).where(SupportThread.chat_id == chat_id, SupportThread.user_id == user.id)
    )
    if thread is not None and not fresh:
        return thread
    topic = await bot.create_forum_topic(chat_id, topic_name(user))
    if thread is None:
        thread = SupportThread(user_id=user.id, chat_id=chat_id, topic_id=topic.message_thread_id)
        session.add(thread)
    else:
        thread.topic_id = topic.message_thread_id
    await session.flush()
    await bot.send_message(chat_id, await _card(session, user), message_thread_id=topic.message_thread_id)
    return thread


async def _copy(bot: Bot, chat_id: int, topic_id: int, messages: list[Message]) -> None:
    if len(messages) == 1:
        await bot.copy_message(chat_id, messages[0].chat.id, messages[0].message_id, message_thread_id=topic_id)
    else:
        await bot.copy_messages(
            chat_id, messages[0].chat.id, [m.message_id for m in messages], message_thread_id=topic_id
        )


async def to_support(bot: Bot, session: AsyncSession, chat_id: int, user: User, messages: list[Message]) -> bool:
    """Copy the user's message (or album) into their topic, opening a new one if the old topic was deleted."""
    try:
        thread = await _thread(bot, session, chat_id, user)
        try:
            await _copy(bot, chat_id, thread.topic_id, messages)
        except TelegramBadRequest as e:
            err = str(e).upper()
            if "TOPIC_CLOSED" in err:
                await bot.reopen_forum_topic(chat_id, thread.topic_id)
            elif any(s in err for s in _TOPIC_GONE):
                thread = await _thread(bot, session, chat_id, user, fresh=True)
            else:
                raise
            await _copy(bot, chat_id, thread.topic_id, messages)
        return True
    except TelegramAPIError as e:
        log.warning("support message from %s not delivered: %s", user.tg_id, e)
        return False


async def thread_user(session: AsyncSession, chat_id: int, topic_id: int) -> User | None:
    thread = await session.scalar(
        select(SupportThread).where(SupportThread.chat_id == chat_id, SupportThread.topic_id == topic_id)
    )
    return await session.get(User, thread.user_id) if thread is not None else None

