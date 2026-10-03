"""The comment the bot leaves under each published post in the channel's discussion group."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message, ReplyParameters

from flowpost.db.models import Channel

log = logging.getLogger(__name__)

MAX_AUTO_COMMENT = 2000


def auto_comment_settings(raw: dict | None) -> dict:
    return {"enabled": False, "html": "", **(raw or {})}


async def send(bot: Bot, channel: Channel, thread_root: Message) -> None:
    """Reply to the copy of a channel post Telegram forwarded into the discussion group, so the reply
    shows up as the first comment under the post."""
    s = auto_comment_settings(channel.auto_comment)
    if not s["enabled"] or not s["html"]:
        return
    try:
        await bot.send_message(
            thread_root.chat.id, s["html"],
            message_thread_id=thread_root.message_thread_id if thread_root.is_topic_message else None,
            reply_parameters=ReplyParameters(message_id=thread_root.message_id, allow_sending_without_reply=True),
        )
    except TelegramAPIError as e:
        log.info("auto comment failed for channel %s: %s", channel.id, e)
