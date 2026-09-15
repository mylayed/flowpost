"""Per-channel paid posting subscriptions and moving one to another channel of the same owner."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.config import Settings
from flowpost.db.models import ChannelQuota, ChannelSubscription
from flowpost.db.types import utcnow
from flowpost.services import analytics
from flowpost.services.billing import limits
from flowpost.services.billing.wallet import debit

PLAN_QUOTAS = ("wm_photo", "wm_video", "ai_text")


async def buy(
    session: AsyncSession, settings: Settings, user_id: int, channel_ids: list[int], posts_per_day: int, days: int,
    stars: int, now: datetime | None = None,
) -> bool:
    """Charge `stars` and extend every channel's plan by `days`; False if the wallet can't cover it."""
    now = now or utcnow()
    if not await debit(session, user_id, stars, kind="spend", ref=f"subscribe:{posts_per_day}:{days}"):
        return False
    plan = settings.posting_plans[posts_per_day]
    for channel_id in channel_ids:
        sub = await session.scalar(
            select(ChannelSubscription).where(ChannelSubscription.channel_id == channel_id).with_for_update()
        )
        start = now
        if sub is None:
            sub = ChannelSubscription(channel_id=channel_id, posts_per_day=posts_per_day, paid_until=now)
            session.add(sub)
        elif sub.paid_until > now:
            left = sub.paid_until - now
            old = settings.posting_plans.get(sub.posts_per_day)
            if sub.posts_per_day != posts_per_day and old:
                # Unused days of another plan are converted by price so switching plans neither loses nor gains value.
                left = left * old["stars"] / plan["stars"]
            start = now + left
        sub.posts_per_day = posts_per_day
        sub.paid_until = start + timedelta(days=days)
        for kind in PLAN_QUOTAS:
            amount = plan.get(kind, 0) * days // 30
            if amount:
                await limits.add(session, channel_id, kind, amount)
    await session.flush()
    analytics.track(
        session, user_id, "subscribe", channels=channel_ids, posts_per_day=posts_per_day, days=days, stars=stars
    )
    return True


async def get(session: AsyncSession, channel_id: int) -> ChannelSubscription | None:
    return await session.scalar(select(ChannelSubscription).where(ChannelSubscription.channel_id == channel_id))


async def by_channel(session: AsyncSession, channel_ids: list[int]) -> dict[int, ChannelSubscription]:
    if not channel_ids:
        return {}
    subs = await session.scalars(select(ChannelSubscription).where(ChannelSubscription.channel_id.in_(channel_ids)))
    return {sub.channel_id: sub for sub in subs}


async def transfer(
    session: AsyncSession, source_id: int, target_id: int, user_id: int, now: datetime | None = None
) -> str | None:
    """Move the source channel's active subscription and extra packs to the target; returns an error code or None."""
    now = now or utcnow()
    sub = await session.scalar(
        select(ChannelSubscription).where(ChannelSubscription.channel_id == source_id).with_for_update()
    )
    if sub is None or sub.paid_until <= now:
        return "not_transferable"
    existing = await session.scalar(
        select(ChannelSubscription).where(ChannelSubscription.channel_id == target_id).with_for_update()
    )
    if existing is not None:
        if existing.paid_until > now:
            return "target_subscribed"
        await session.delete(existing)
        await session.flush()
    sub.channel_id = target_id

    target_quotas = {
        quota.kind: quota
        for quota in await session.scalars(
            select(ChannelQuota).where(ChannelQuota.channel_id == target_id).with_for_update()
        )
    }
    source_quotas = (await session.scalars(
        select(ChannelQuota).where(ChannelQuota.channel_id == source_id).with_for_update()
    )).all()
    for quota in source_quotas:
        if quota.kind in target_quotas:
            target_quotas[quota.kind].remaining += quota.remaining
            await session.delete(quota)
        else:
            quota.channel_id = target_id
    await session.flush()
    analytics.track(session, user_id, "sub_transfer", source=source_id, target=target_id)
    return None
