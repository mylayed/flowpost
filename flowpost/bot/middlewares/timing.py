from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

log = logging.getLogger(__name__)


class TimingMiddleware(BaseMiddleware):
    """Logs an update that took longer than `threshold` seconds to handle.

    The editor answers a message with two Telegram calls and a dozen small queries, so anything much
    slower comes from outside the handler — a watermark being drawn, a large file being re-uploaded, or
    Telegram itself. This puts a number on it instead of a guess.
    """

    def __init__(self, threshold: float = 3.0):
        self.threshold = threshold

    @staticmethod
    def _what(event: TelegramObject) -> str:
        """A short label for the log line; never raises — an update we can't classify is just "?"."""
        try:
            if not isinstance(event, Update):
                return type(event).__name__
            kind = event.event_type
            message = event.message
            if message is not None:
                return f"{kind}:{message.content_type}:album" if message.media_group_id else f"{kind}:{message.content_type}"
            if event.callback_query is not None:
                return f"{kind}:{(event.callback_query.data or '').split(':', 1)[0]}"
            return kind
        except Exception:  # noqa: BLE001 - a label is never worth breaking an update over
            return "?"

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        started = time.monotonic()
        try:
            return await handler(event, data)
        finally:
            elapsed = time.monotonic() - started
            if elapsed >= self.threshold:
                user = data.get("event_from_user")
                log.warning(
                    "slow update: %s took %.1fs (user %s)", self._what(event), elapsed,
                    getattr(user, "id", "?"),
                )
