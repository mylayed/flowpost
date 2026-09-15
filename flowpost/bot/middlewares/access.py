from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.dispatcher.flags import get_flag
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Cp, Ed
from flowpost.bot.keyboards.common import paywall_kb
from flowpost.config import Settings
from flowpost.db.models import Channel, Post, User
from flowpost.db.repo import posts as posts_repo
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services.billing import entitlements
from flowpost.services.billing.subscriptions import get_access


class AccessMiddleware(BaseMiddleware):
    """Guards flagged handlers: `paid` (AI) needs an active trial or subscription, and `publish`
    (publish, schedule) needs every target channel to still have a plan — paid, trial or free."""

    @staticmethod
    async def _post_id(event: TelegramObject, data: dict[str, Any]) -> int | None:
        """The post a guarded action targets, so a delegated admin is checked against the real owner."""
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

    @staticmethod
    async def _channels_have_plan(session: AsyncSession, settings: Settings, post: Post, owner: User) -> bool:
        now = utcnow()
        channels = (await session.scalars(select(Channel).where(Channel.id.in_(post.channel_ids)))).all()
        for channel in channels:
            if (await entitlements.for_channel(session, settings, channel, owner, now)).plan == "none":
                return False
        return True

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        paid = get_flag(data, "paid")
        publish = get_flag(data, "publish")
        if not (paid or publish):
            return await handler(event, data)
        user = data.get("user")
        if user is None:
            return None
        session = data["session"]
        post = None
        access_for = user
        post_id = await self._post_id(event, data)
        if post_id:
            post = await posts_repo.get_post(session, user.id, post_id)
            if post is not None and post.owner_id != user.id:
                owner = await session.get(User, post.owner_id)
                if owner is not None:
                    access_for = owner
        if paid:
            access = await get_access(session, access_for)
            if access.active:
                data["access"] = access
                return await handler(event, data)
        elif post is None or await self._channels_have_plan(session, data["settings"], post, access_for):
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer(t("paywall.short"), show_alert=True)
            if event.message:
                await event.message.answer(t("paywall.text"), reply_markup=paywall_kb(data["settings"]))
        elif isinstance(event, Message):
            await event.answer(t("paywall.text"), reply_markup=paywall_kb(data["settings"]))
        return None
