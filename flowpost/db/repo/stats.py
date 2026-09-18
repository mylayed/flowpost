from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.config import Settings
from flowpost.db.models import Channel, Payment, Publication, Subscription, SupportThread, UsageEvent, User


async def _count(session: AsyncSession, stmt) -> int:
    return int(await session.scalar(stmt) or 0)


async def admin_stats(session: AsyncSession, now: datetime, settings: Settings) -> dict:
    day, week = now - timedelta(days=1), now - timedelta(days=7)
    users_total = await _count(session, select(func.count(User.id)))
    subs_by_provider = dict(
        (await session.execute(
            select(Subscription.provider, func.count(Subscription.id))
            .where(Subscription.current_period_end > now, Subscription.status.in_(("active", "cancelled")))
            .group_by(Subscription.provider)
        )).all()
    )
    paid_total = sum(subs_by_provider.values())
    paying_ever = await _count(session, select(func.count(func.distinct(Payment.user_id))))
    return {
        "users_total": users_total,
        "users_new_7d": await _count(session, select(func.count(User.id)).where(User.created_at >= week)),
        "active_7d": await _count(session, select(func.count(User.id)).where(User.last_seen_at >= week)),
        "trials_active": await _count(session, select(func.count(User.id)).where(User.trial_ends_at > now)),
        "subs_active": paid_total,
        "subs_by_provider": subs_by_provider,
        "conversion_pct": round(100 * paying_ever / users_total, 1) if users_total else 0.0,
        "channels_active": await _count(
            session, select(func.count(Channel.id)).where(Channel.is_active.is_(True), Channel.kind == "channel")
        ),
        # groups the bot posts to; a channel's comments group isn't one of them
        "groups_active": await _count(session, select(func.count(Channel.id)).where(
            Channel.is_active.is_(True), Channel.kind == "group",
            Channel.chat_id.not_in(select(Channel.discussion_chat_id).where(Channel.discussion_chat_id.is_not(None))),
        )),
        "published_24h": await _count(
            session, select(func.count(Publication.id)).where(Publication.published_at >= day)
        ),
        "published_7d": await _count(
            session, select(func.count(Publication.id)).where(Publication.published_at >= week)
        ),
        "scheduled": await _count(
            session, select(func.count(Publication.id)).where(Publication.status == "pending")
        ),
        "ai_calls_24h": await _count(
            session,
            select(func.count(UsageEvent.id)).where(UsageEvent.kind == "ai_call", UsageEvent.created_at >= day),
        ),
        **await _support_stats(session, week, settings),
    }


async def _support_stats(session: AsyncSession, week: datetime, settings: Settings) -> dict:
    """Users who wrote to the support group: all of them, active in the last 7 days, and still awaiting a reply."""
    threads = select(func.count(SupportThread.id)).where(SupportThread.chat_id == settings.support_chat_id)
    return {
        "support_users": await _count(session, threads),
        "support_7d": await _count(session, threads.where(SupportThread.last_user_at >= week)),
        "support_waiting": await _count(session, threads.where(
            SupportThread.last_user_at.is_not(None),
            (SupportThread.last_reply_at.is_(None)) | (SupportThread.last_reply_at < SupportThread.last_user_at),
        )),
    }


async def active_chats(session: AsyncSession) -> tuple[list[tuple[Channel, User]], list[tuple[Channel, User]]]:
    """Every active channel and every group the bot posts to (comments groups left out), each chat once, with its
    owner — for the admin's /chats."""
    comments = select(Channel.discussion_chat_id).where(Channel.discussion_chat_id.is_not(None))
    rows = (await session.execute(
        select(Channel, User).join(User, User.id == Channel.owner_id)
        .where(Channel.is_active.is_(True), Channel.kind.in_(("channel", "group")))
        .where((Channel.kind == "channel") | Channel.chat_id.not_in(comments))
        .order_by(func.lower(Channel.title), Channel.id)
    )).tuples().all()
    seen: set[int] = set()
    channels, groups = [], []
    for channel, owner in rows:
        if channel.chat_id in seen:
            continue
        seen.add(channel.chat_id)
        (channels if channel.kind == "channel" else groups).append((channel, owner))
    return channels, groups
