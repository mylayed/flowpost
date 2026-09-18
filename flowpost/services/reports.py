"""The Monday report for a channel: growth, the week's best posts, the best time to post and gaps in the plan."""
from __future__ import annotations

import html
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Channel, MemberCount, Post, User
from flowpost.db.repo import publications as pubs_repo
from flowpost.i18n import t
from flowpost.services import growth
from flowpost.services.delivery import engagement_score, publication_message_ids, reactions_total
from flowpost.services.html_sanitize import snippet
from flowpost.services.posts import message_link, part_preview_text
from flowpost.services.slots import WEEKDAYS, day_bounds_utc, fmt_date, tz_of
from flowpost.services.smart_time import best_slots

REPORT_WEEKDAY = 0  # Monday
REPORT_TIME = time(10, 0)
TOP_N = 3


def report_due_since(owner: User, now: datetime) -> datetime | None:
    """Today's report time if it's Monday after 10:00 in the owner's zone, else None. Reports only go out on
    Mondays, so a new channel (or the bot back after a pause) waits for the next one instead of getting it midweek."""
    local = now.astimezone(tz_of(owner.tz))
    due = datetime.combine(local.date(), REPORT_TIME, tzinfo=tz_of(owner.tz))
    return due if local.weekday() == REPORT_WEEKDAY and local >= due else None


async def member_growth(session: AsyncSession, channel_id: int, today: date) -> tuple[int | None, int | None]:
    """Subscribers now and the change against the reading closest to a week ago (None where unknown)."""
    rows = (await session.execute(
        select(MemberCount.day, MemberCount.count)
        .where(MemberCount.channel_id == channel_id, MemberCount.day >= today - timedelta(days=8))
        .order_by(MemberCount.day)
    )).all()
    if not rows:
        return None, None
    current = rows[-1][1]
    week_ago = [c for d, c in rows if d <= today - timedelta(days=7)]
    base = week_ago[-1] if week_ago else (rows[0][1] if rows[0][0] < rows[-1][0] else None)
    return current, (current - base if base is not None else None)


async def weekly_report(session: AsyncSession, channel: Channel, owner: User, now: datetime) -> str:
    lang = owner.lang
    zone = tz_of(owner.tz)
    today = now.astimezone(zone).date()
    since = now - timedelta(days=7)
    lines = [
        t("wr.title", locale=lang, title=html.escape(channel.title)),
        t("wr.period", locale=lang, start=fmt_date(today - timedelta(days=7), lang), end=fmt_date(today - timedelta(days=1), lang)),
        "",
    ]

    members, delta = await member_growth(session, channel.id, now.date())
    if members is not None:
        change = f" ({delta:+d})" if delta is not None else ""
        lines.append(t("wr.members", locale=lang, n=members, change=change))

    pubs = await pubs_repo.published_between(session, owner.id, since, now, channel_ids=[channel.id])
    lines.append(t(
        "wr.summary", locale=lang, posts=len(pubs), reactions=sum(reactions_total(p) for p in pubs),
        comments=sum(p.comments_count or 0 for p in pubs),
    ))

    top = [p for p in sorted(pubs, key=engagement_score, reverse=True) if engagement_score(p)][:TOP_N]
    if top:
        lines += ["", t("wr.top", locale=lang)]
        for i, pub in enumerate(top, 1):
            post = await session.get(Post, pub.post_id)
            title = snippet(part_preview_text(post.parts[0]), 40) if post and post.parts else ""
            title = html.escape(title) if title else t("stats.no_text", locale=lang)
            ids = publication_message_ids(pub)
            if ids:
                title = f'<a href="{message_link(channel, ids[0])}">{title}</a>'
            lines.append(t("wr.top_row", locale=lang, n=i, title=title,
                           reactions=reactions_total(pub), comments=pub.comments_count or 0))

    joins = await growth.joins_since(session, channel.id, since)
    if joins:
        lines += ["", t("wr.links", locale=lang)]
        lines += [t("wr.link_row", locale=lang, name=html.escape(name), n=n) for name, n in joins[:5]]

    slots = await best_slots(session, owner.id, [channel.id], owner.tz)
    if slots:
        names = WEEKDAYS.get(lang, WEEKDAYS["uk"])
        lines += ["", t("wr.best_time", locale=lang, slots=" • ".join(f"{names[s.weekday]} {s.hour:02d}:00" for s in slots))]

    empty = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        start, end = day_bounds_utc(day, owner.tz)
        if not await pubs_repo.pending_between(session, owner.id, start, end, channel_ids=[channel.id]):
            empty.append(fmt_date(day, lang))
    lines.append("")
    lines.append(t("wr.plan_full", locale=lang) if not empty else t("wr.plan_gaps", locale=lang, days=", ".join(empty)))
    return "\n".join(lines)
