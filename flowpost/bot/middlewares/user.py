from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from flowpost.config import Settings
from flowpost.db.repo import users as users_repo
from flowpost.i18n import set_locale


class UserMiddleware(BaseMiddleware):
    """Loads (or registers) the FlowPost user — the tenant — and activates their language."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        chat = data.get("event_chat")
        is_update = isinstance(event, Update)
        allowed_context = (
            chat is None
            or chat.type == "private"
            or (is_update and (event.my_chat_member is not None))
        )
        set_locale(self.settings.default_lang)
        if tg_user is not None and not tg_user.is_bot and allowed_context:
            user, created = await users_repo.get_or_create(data["session"], tg_user, self.settings)
            data["user"] = user
            data["user_created"] = created
            set_locale(user.lang)
        return await handler(event, data)
