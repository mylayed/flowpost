"""What a channel may publish right now: its plan (paid, trial, free) and how many posts it has left."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.config import Settings
from flowpost.db.models import Channel, Publication, User
from flowpost.services.billing import channel_subs
from flowpost.services.billing.subscriptions import get_subscription
from flowpost.services.slots import day_bounds_utc, tz_of


@dataclass
class Entitlement:
    plan: str  # paid | trial | free | none
    posts_limit: int | None  # None = unlimited
    window: str  # day | trial | none
    until: datetime | None = None
    posts_per_day: int | None = None


async def _premium(session: AsyncSession, channel: Channel, now: datetime, trial_posts: int) -> Entitlement | None:
    """The channel's paid plan or running trial, or None if it has neither."""
    sub = await channel_subs.get(session, channel.id)
    if sub is not None and sub.paid_until > now:
        return Entitlement("paid", sub.posts_per_day, "day", sub.paid_until, sub.posts_per_day)
    account = await get_subscription(session, channel.owner_id)
    if account is not None and account.status in ("active", "cancelled") and account.current_period_end > now:
        # Account-wide subscriptions bought before per-channel plans stay unlimited until they run out.
        return Entitlement("paid", None, "none", account.current_period_end)
    if channel.trial_ends_at is not None and channel.trial_ends_at > now:
        return Entitlement("trial", trial_posts, "trial", channel.trial_ends_at)
    return None


async def for_channel(
    session: AsyncSession, settings: Settings, channel: Channel, owner: User, now: datetime
) -> Entitlement:
    premium = await _premium(session, channel, now, settings.trial_posts)
    if premium is not None:
        return premium
    if settings.free_posts_per_day > 0:
        return Entitlement("free", settings.free_posts_per_day, "day")
    return Entitlement("none", 0, "none")


@dataclass
class Coverage:
    """Every paid plan and trial the channel has running right now, each with its own end date."""

    channel_until: datetime | None = None  # the channel's own paid plan
    account_until: datetime | None = None  # an account-wide subscription bought before per-channel plans
    trial_until: datetime | None = None

    @property
    def until(self) -> datetime | None:
        """When the channel's last running plan or trial ends. They all run now, so they overlap without gaps."""
        return max((d for d in (self.channel_until, self.account_until, self.trial_until) if d), default=None)


async def coverage(session: AsyncSession, channel: Channel, now: datetime) -> Coverage:
    result = Coverage()
    sub = await channel_subs.get(session, channel.id)
    if sub is not None and sub.paid_until > now:
        result.channel_until = sub.paid_until
    account = await get_subscription(session, channel.owner_id)
    if account is not None and account.status in ("active", "cancelled") and account.current_period_end > now:
        result.account_until = account.current_period_end
    if channel.trial_ends_at is not None and channel.trial_ends_at > now:
        result.trial_until = channel.trial_ends_at
    return result


def has_extras(entitlement: Entitlement) -> bool:
    """Watermarks, AI, multiposting and auto-repeat come with a paid plan or the trial, not with the free plan."""
    return entitlement.plan in ("paid", "trial")


async def extras_allowed(session: AsyncSession, channels: list[Channel], now: datetime) -> bool:
    """Whether every one of `channels` is on a paid plan or in its trial (False for no channels)."""
    for channel in channels:
        if await _premium(session, channel, now, 0) is None:
            return False
    return bool(channels)


async def published_count(session: AsyncSession, channel_ids: list[int], start: datetime, end: datetime) -> int:
    if not channel_ids:
        return 0
    return int(await session.scalar(
        select(func.count(Publication.id)).where(
            Publication.channel_id.in_(channel_ids),
            Publication.status == "published",
            Publication.published_at >= start,
            Publication.published_at < end,
        )
    ) or 0)


async def posts_left(
    session: AsyncSession, settings: Settings, channel: Channel, owner: User, entitlement: Entitlement, now: datetime
) -> int | None:
    """Posts the channel may still publish in its window (today, or the whole trial); None means unlimited."""
    if entitlement.plan == "none":
        return 0
    if entitlement.posts_limit is None:
        return None
    if entitlement.window == "trial":
        start, end = channel.created_at, entitlement.until
    else:
        start, end = day_bounds_utc(now.astimezone(tz_of(owner.tz)).date(), owner.tz)
    left = entitlement.posts_limit - await published_count(session, [channel.id], start, end)
    if entitlement.plan == "free":
        # The free daily allowance is also shared by all of the owner's channels that are on the free plan.
        owner_channels = (await session.scalars(select(Channel).where(Channel.owner_id == owner.id))).all()
        free_ids = [
            c.id for c in owner_channels
            if (await for_channel(session, settings, c, owner, now)).plan == "free"
        ]
        left = min(left, settings.free_posts_per_day - await published_count(session, free_ids, start, end))
    return max(left, 0)
