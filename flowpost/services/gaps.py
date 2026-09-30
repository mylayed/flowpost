"""Reminders that tomorrow has nothing scheduled.

An opt-in channel setting. Once a day, from 10:00 in the owner's zone, the channel's tomorrow is checked; if nothing is
scheduled for it, the owner and the admins who may post get a reminder, but never more often than every
`REMIND_EVERY_DAYS` days, so a channel that posts rarely on purpose isn't nagged daily.
"""
from __future__ import annotations

import html
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Channel, Publication, User
from flowpost.db.repo import channel_admins as channel_admins_repo
from flowpost.i18n import t
from flowpost.services import ideas as ideas_service
from flowpost.services.slots import day_bounds_utc, fmt_date, tz_of

REMIND_TIME = time(10, 0)
REMIND_EVERY_DAYS = 3
LOOKAHEAD_DAYS = 3  # tomorrow and the two days after it; the reminder names the empty ones
DORMANT_AFTER = timedelta(days=14)
PLANNED = ("pending", "paused", "publishing")


def check_day(owner: User, now: datetime) -> date | None:
    """Today in the owner's zone once it's past the reminder time, else None."""
    local = now.astimezone(tz_of(owner.tz))
    return local.date() if local.time() >= REMIND_TIME else None


def due_again(channel: Channel, today: date) -> bool:
    """False while the last reminder is fewer than `REMIND_EVERY_DAYS` days old."""
    return channel.gap_reminded_on is None or (today - channel.gap_reminded_on).days >= REMIND_EVERY_DAYS


async def is_dormant(session: AsyncSession, channel: Channel, now: datetime) -> bool:
    """Nothing published lately and nothing queued: the owner has stopped using the bot for this channel."""
    recent = await session.scalar(
        select(func.count(Publication.id)).where(
            Publication.channel_id == channel.id,
            ((Publication.status == "published") & (Publication.published_at >= now - DORMANT_AFTER))
            | ((Publication.status.in_(PLANNED)) & (Publication.run_at >= now)),
        )
    )
    return not recent


async def empty_days(session: AsyncSession, channel: Channel, owner: User, today: date) -> list[date]:
    """The coming days (from tomorrow) in the owner's zone on which nothing is scheduled for the channel."""
    days = [today + timedelta(days=i) for i in range(1, LOOKAHEAD_DAYS + 1)]
    start, _ = day_bounds_utc(days[0], owner.tz)
    _, end = day_bounds_utc(days[-1], owner.tz)
    runs = (await session.scalars(
        select(Publication.run_at).where(
            Publication.channel_id == channel.id,
            Publication.status.in_(PLANNED),
            Publication.run_at >= start,
            Publication.run_at < end,
        )
    )).all()
    zone = tz_of(owner.tz)
    planned = {run.astimezone(zone).date() for run in runs}
    return [d for d in days if d not in planned]


async def recipients(session: AsyncSession, channel: Channel, owner: User) -> list[tuple[User, bool]]:
    """Who gets the reminder: the owner and every admin allowed to post who hasn't blocked the bot. The flag says
    whether that person may switch the reminders off, which is a channel setting."""
    result = [(owner, True)]
    for grant, user in await channel_admins_repo.list_admins(session, channel.id):
        if grant.can_posts and not user.is_blocked and user.id != owner.id:
            result.append((user, grant.can_settings))
    return result


def days_text(days: list[date], today: date, lang: str) -> str:
    return ", ".join(
        t("gap.tomorrow", locale=lang) if d == today + timedelta(days=1) else fmt_date(d, lang) for d in days
    )


async def reminder_text(
    session: AsyncSession, channel: Channel, recipient: User, days: list[date], today: date,
) -> str:
    lang = recipient.lang
    lines = [t("gap.text", locale=lang, title=html.escape(channel.title), days=days_text(days, today, lang))]
    ideas = len(await ideas_service.for_channel(session, channel))
    if ideas:
        lines.append(t("gap.ideas", locale=lang, n=ideas))
    return "\n\n".join(lines)
