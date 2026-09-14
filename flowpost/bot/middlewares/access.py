from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.dispatcher.flags import get_flag
from aiogram.types import CallbackQuery, Message, TelegramObject

from flowpost.bot.callbacks import Cp, Ed
from flowpost.bot.keyboards.common import paywall_kb
from flowpost.db.models import User
from flowpost.db.repo import posts as posts_repo
from flowpost.i18n import t
from flowpost.services.billing.subscriptions import get_access


class AccessMiddleware(BaseMiddleware):
    """Blocks handlers flagged `paid` (publish, schedule, AI) when trial and subscription are over."""

    @staticmethod
    async def _post_id(event: TelegramObject, data: dict[str, Any]) -> int | None:
        """The post a paid action targets, so a delegated admin is checked against the real owner's access."""
        if isinstance(event, CallbackQuery) and event.data:
            try:
                if event.data.startswith("ed:"):
                    return Ed.unpack(event.data).p
                if event.data.startswith("cp:"):
                    return Cp.unpack(event.data).id or None
            except (ValueError, TypeError):
                return None
            return None
        state = data.get("state")
        if state is None:
            return None
        pid = (await state.get_data()).get("post_id")
        return int(pid) if pid else None

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not get_flag(data, "paid"):
            return await handler(event, data)
        user = data.get("user")
        if user is None:
            return None
        session = data["session"]
        access_for = user
        post_id = await self._post_id(event, data)
        if post_id:
            post = await posts_repo.get_post(session, user.id, post_id)
            if post is not None and post.owner_id != user.id:
                owner = await session.get(User, post.owner_id)
                if owner is not None:
                    access_for = owner
        access = await get_access(session, access_for)
        if access.active:
            data["access"] = access
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer(t("paywall.short"), show_alert=True)
            if event.message:
                await event.message.answer(t("paywall.text"), reply_markup=paywall_kb())
        elif isinstance(event, Message):
            await event.answer(t("paywall.text"), reply_markup=paywall_kb())
        return None
