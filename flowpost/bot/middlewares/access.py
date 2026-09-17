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
from flowpost.services.billing.subscriptions import Access


class AccessMiddleware(BaseMiddleware):
    """Guards flagged handlers: `paid` (AI) needs every channel of the post on a paid plan or trial, and `publish`
    (publish, schedule) needs every target channel to still have a plan — paid, trial or free — and, for
    multiposting or auto-repeat, a paid plan or trial."""

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
    async def _channels_have_plan(session: AsyncSession, settings: Settings, post: Post, owner: User) -> str | None:
        """None if the post may go out, otherwise the paywall reason: "plan" (nothing left) or "extras"
        (multiposting or auto-repeat on a channel that's on the free plan)."""
        now = utcnow()
        channels = (await session.scalars(select(Channel).where(Channel.id.in_(post.channel_ids)))).all()
        needs_extras = len(post.channel_ids) > 1 or bool(post.repeat and post.repeat.active)
        for channel in channels:
            entitlement = await entitlements.for_channel(session, settings, channel, owner, now)
            if entitlement.plan == "none":
                return "plan"
            if needs_extras and not entitlements.has_extras(entitlement):
                return "extras"
        return None

    @staticmethod
    async def _ai_access(session: AsyncSession, settings: Settings, post: Post, owner: User) -> Access | None:
        """AI comes with the channels' paid plan or trial; every channel of the post needs one."""
        now = utcnow()
        channels = (await session.scalars(select(Channel).where(Channel.id.in_(post.channel_ids)))).all()
        if not channels:
            return None
        plans = [await entitlements.for_channel(session, settings, c, owner, now) for c in channels]
        if not all(entitlements.has_extras(e) for e in plans):
            return None
        kind = "paid" if all(e.plan == "paid" for e in plans) else "trial"
        return Access(True, kind, min((e.until for e in plans if e.until), default=None), None)

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
        settings = data["settings"]
        reason = "plan"
        if paid:
            access = await self._ai_access(session, settings, post, access_for) if post is not None else None
            if access is not None:
                data["access"] = access
                return await handler(event, data)
            reason = "extras"
        elif post is None:
            return await handler(event, data)
        else:
            reason = await self._channels_have_plan(session, settings, post, access_for)
            if reason is None:
                return await handler(event, data)
        short, text = ("paywall.short", "paywall.text") if reason == "plan" else ("paywall.extras_short", "paywall.extras")
        if isinstance(event, CallbackQuery):
            await event.answer(t(short), show_alert=True)
            if event.message:
                await event.message.answer(t(text), reply_markup=paywall_kb(settings))
        elif isinstance(event, Message):
            await event.answer(t(text), reply_markup=paywall_kb(settings))
        return None
