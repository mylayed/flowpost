from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, Update

from flowpost.services.posts import MAX_MEDIA


class _Group:
    __slots__ = ("messages", "arrived")

    def __init__(self, first: Message):
        self.messages = [first]
        self.arrived = asyncio.Event()


class AlbumMiddleware(BaseMiddleware):
    """Collects messages of one media group and passes them to the handler once, as data["album"].

    Telegram delivers an album as separate updates tens of milliseconds apart, so the first one has to
    wait for the rest. The wait is a quiet window that restarts with every item instead of a fixed pause:
    the usual two- or three-photo album opens the editor about half a second sooner, and a full album of
    `MAX_MEDIA` doesn't wait at all once its last item is in. `max_wait` caps a trickling album.

    Registered before the DB session middleware, so the wait doesn't hold a pooled connection and the
    messages that only join the group never touch the database.
    """

    def __init__(self, quiet: float = 0.25, max_wait: float = 2.0):
        self.quiet = quiet
        self.max_wait = max_wait
        self._albums: dict[str, _Group] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        message = event.message if isinstance(event, Update) else event
        if not isinstance(message, Message) or not message.media_group_id:
            return await handler(event, data)
        key = f"{message.chat.id}:{message.media_group_id}"
        group = self._albums.get(key)
        if group is not None:
            group.messages.append(message)
            group.arrived.set()
            return None
        group = self._albums[key] = _Group(message)
        try:
            await self._collect(group)
        finally:
            self._albums.pop(key, None)
        data["album"] = sorted(group.messages, key=lambda m: m.message_id)
        return await handler(event, data)

    async def _collect(self, group: _Group) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.max_wait
        while len(group.messages) < MAX_MEDIA:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            # Clearing before reading the count is what makes this safe: an item that slips in right
            # here is already counted, so at worst we wait one more quiet window for nothing.
            group.arrived.clear()
            try:
                await asyncio.wait_for(group.arrived.wait(), min(self.quiet, remaining))
            except asyncio.TimeoutError:
                return
