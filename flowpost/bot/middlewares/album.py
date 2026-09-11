from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class AlbumMiddleware(BaseMiddleware):
    """Collects messages of one media group and passes them to the handler once, as data["album"]."""

    def __init__(self, latency: float = 0.8):
        self.latency = latency
        self._albums: dict[str, list[Message]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.media_group_id:
            return await handler(event, data)
        key = f"{event.chat.id}:{event.media_group_id}"
        if key in self._albums:
            self._albums[key].append(event)
            return None
        self._albums[key] = [event]
        await asyncio.sleep(self.latency)
        messages = self._albums.pop(key, [event])
        data["album"] = sorted(messages, key=lambda m: m.message_id)
        return await handler(event, data)
