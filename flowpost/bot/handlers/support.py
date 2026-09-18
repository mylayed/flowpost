"""The support group: the team writes in a user's topic and the bot passes it on to that user."""
from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import BaseFilter, Command
from aiogram.types import InlineKeyboardMarkup, Message, ReactionTypeEmoji
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import St
from flowpost.bot.handlers.admin import IsAdmin
from flowpost.bot.keyboards.common import btn, markup
from flowpost.config import Settings
from flowpost.db.models import User
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services.support import find_thread

log = logging.getLogger(__name__)
router = Router(name="support")

# Content a reply is copied with a caption of its own, so the «Відповідь підтримки» header goes into it.
CAPTIONED = {"photo", "video", "animation", "document", "audio", "voice"}
RELAYED = CAPTIONED | {"text", "sticker", "video_note", "location", "contact", "venue", "dice"}


class InSupportChat(BaseFilter):
    async def __call__(self, message: Message, settings: Settings) -> bool:
        return settings.support_chat_id is not None and message.chat.id == settings.support_chat_id


@router.message(Command("supportchat"), F.chat.type == "supergroup", IsAdmin())
async def cmd_supportchat(message: Message, bot: Bot, settings: Settings) -> None:
    """Setup helper: the group's id for SUPPORT_CHAT_ID and whether the bot can open topics in it."""
    me = await bot.me()
    member = await bot.get_chat_member(message.chat.id, me.id)
    can_topics = str(member.status) == "creator" or bool(getattr(member, "can_manage_topics", False))
    connected = settings.support_chat_id == message.chat.id
    await message.answer(
        f"SUPPORT_CHAT_ID=<code>{message.chat.id}</code>\n\n"
        f"{'✅' if message.chat.is_forum else '❌'} Теми (Topics) увімкнено\n"
        f"{'✅' if can_topics else '❌'} Бот — адмін із правом «Керування темами»\n"
        f"{'✅ Цю групу підключено до підтримки' if connected else 'ℹ️ Вкажіть цей id у SUPPORT_CHAT_ID і перезапустіть бота'}"
    )


def reply_kb(user: User) -> InlineKeyboardMarkup:
    return markup([[btn(t("set.support_reply_btn", locale=user.lang), St(a="support", v="reply"))]])


async def to_user(bot: Bot, user: User, message: Message) -> None:
    """Send the team's reply to the user as the bot, headed «Відповідь підтримки»."""
    kb = reply_kb(user)
    if message.text is not None:
        text = t("set.support_answer", locale=user.lang, text=message.html_text)
        await bot.send_message(user.tg_id, text, reply_markup=kb)
        return
    caption = None
    if message.content_type in CAPTIONED:
        caption = t("set.support_answer", locale=user.lang, text=message.html_text if message.caption else "").rstrip()
    await bot.copy_message(user.tg_id, message.chat.id, message.message_id, caption=caption, reply_markup=kb)


@router.message(InSupportChat(), F.is_topic_message, F.content_type.in_(RELAYED))
async def on_team_reply(message: Message, bot: Bot, session: AsyncSession) -> None:
    if message.from_user is None or message.from_user.is_bot or (message.text or "").startswith("/"):
        return
    thread = await find_thread(session, message.chat.id, message.message_thread_id)
    user = await session.get(User, thread.user_id) if thread is not None else None
    if thread is None or user is None:
        await message.reply("⚠️ Ця тема не пов'язана з жодним користувачем — повідомлення нікуди не надіслано.")
        return
    try:
        await to_user(bot, user, message)
    except TelegramForbiddenError:
        await message.reply("⛔️ Користувач заблокував бота — повідомлення не доставлено.")
        return
    except TelegramAPIError as e:
        log.warning("support reply to %s failed: %s", user.tg_id, e)
        await message.reply(f"⚠️ Не вдалося доставити: {html.escape(str(e))}")
        return
    thread.last_reply_at = utcnow()
    try:
        await bot.set_message_reaction(message.chat.id, message.message_id, [ReactionTypeEmoji(emoji="👍")])
    except TelegramAPIError:
        pass


@router.message(InSupportChat())
async def on_other_support_chat_message(message: Message) -> None:
    """Service messages, the General topic, notes: they stay in the group and don't reach other handlers."""
