from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.dispatcher.flags import get_flag
from aiogram.types import CallbackQuery, Message, TelegramObject

from flowpost.bot.keyboards.common import paywall_kb
from flowpost.i18n import t
from flowpost.services.billing.subscriptions import get_access


class AccessMiddleware(BaseMiddleware):
    """Blocks handlers flagged `paid` (publish, schedule, AI) when trial and subscription are over."""

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
        access = await get_access(data["session"], user)
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
