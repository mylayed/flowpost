"""Drops premium (custom) emoji from everything the bot sends.

Telegram only accepts `custom_emoji` entities from bots that bought a username on Fragment; for any
other bot the whole `sendMessage` fails. Admins with Telegram Premium can still write such emoji into
posts and signatures, and `Message.html_text` keeps them as `<tg-emoji emoji-id="…">😀</tg-emoji>`, so
we store the id (posts start rendering it as soon as PREMIUM_EMOJI is turned on) and strip the tag on
the way out. Stripping happens at the session boundary because the same text reaches Telegram from the
publisher, the editor preview and the channel settings panels.
"""
from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.methods import Response, TelegramMethod
from aiogram.methods.base import TelegramType

from flowpost.services.html_sanitize import strip_custom_emoji

_TEXTS = ("text", "caption")
_ENTITIES = ("entities", "caption_entities")


def _changes(obj: Any) -> dict[str, Any]:
    """The text and entity fields of `obj` that carry custom emoji, with the emoji taken out."""
    out: dict[str, Any] = {}
    for name in _TEXTS:
        value = getattr(obj, name, None)
        if isinstance(value, str):
            cleaned = strip_custom_emoji(value)
            if cleaned != value:
                out[name] = cleaned
    for name in _ENTITIES:
        value = getattr(obj, name, None)
        if isinstance(value, list):
            kept = [e for e in value if getattr(e, "type", None) != "custom_emoji"]
            if len(kept) != len(value):
                out[name] = kept or None
    return out


class StripCustomEmojiMiddleware(BaseRequestMiddleware):
    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        for name, value in _changes(method).items():
            setattr(method, name, value)  # methods are mutable, unlike the frozen types below
        # send_media_group carries a list, edit_message_media a single item; both hold their own captions.
        media = getattr(method, "media", None)
        items = media if isinstance(media, list) else [media]
        cleaned = [i.model_copy(update=_changes(i)) if hasattr(i, "caption") else i for i in items]
        if cleaned != items:
            method.media = cleaned if isinstance(media, list) else cleaned[0]
        return await make_request(bot, method)
