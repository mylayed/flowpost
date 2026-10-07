"""Warn when a post or an ad is about to go out within an hour of another one in the same channel — whoever put that
one there, the channel's owner or one of its admins."""
from __future__ import annotations

import html
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Channel, Post, Publication
from flowpost.i18n import t
from flowpost.services.html_sanitize import snippet
from flowpost.services.posts import options_of, part_icon, part_preview_text
from flowpost.services.slots import fmt_date, fmt_hm, tz_of

WINDOW = timedelta(hours=1)
QUEUED_STATUSES = ("pending", "publishing", "paused")


@dataclass
class Conflict:
    channel: Channel
    at: datetime
    post: Post


async def find_conflicts(
    session: AsyncSession, exclude: Collection[int], channels: list[Channel], at: datetime
) -> list[Conflict]:
    """Posts other than `exclude` queued or published in `channels` within `WINDOW` before or after `at`."""
    by_id = {c.id: c for c in channels}
    if not by_id:
        return []
    start, end = at - WINDOW, at + WINDOW
    queued = Publication.status.in_(QUEUED_STATUSES) & (Publication.run_at >= start) & (Publication.run_at <= end)
    published = (
        (Publication.status == "published")
        & Publication.deleted.is_(False)
        & (Publication.published_at >= start)
        & (Publication.published_at <= end)
    )
    pubs = (await session.scalars(
        select(Publication).where(
            Publication.channel_id.in_(list(by_id)), Publication.post_id.not_in(list(exclude)), queued | published,
        )
    )).all()
    found: dict[tuple[int, int], Conflict] = {}
    for pub in pubs:
        when = pub.published_at if pub.status == "published" and pub.published_at else pub.run_at
        key = (pub.channel_id, pub.post_id)
        if key in found and abs(found[key].at - at) <= abs(when - at):
            continue
        other = await session.get(Post, pub.post_id)
        if other is not None:
            found[key] = Conflict(channel=by_id[pub.channel_id], at=when, post=other)
    return sorted(found.values(), key=lambda c: (c.at, c.channel.title))


def _describe(post: Post, lang: str) -> str:
    if post.parts:
        first = post.parts[0]
        text = html.escape(snippet(part_preview_text(first), 32))
        if text:
            return f"{part_icon(first)} {text}"
    advertiser = options_of(post).get("ad_advertiser") if post.is_ad else None
    if advertiser:
        return html.escape(advertiser)
    return t("parts.no_text", locale=lang)


def warning_text(conflicts: list[Conflict], at: datetime, tz_name: str, lang: str) -> str:
    zone = tz_of(tz_name)
    day = at.astimezone(zone).date()
    lines = [t("conflict.title", locale=lang)]
    for c in conflicts:
        local = c.at.astimezone(zone)
        when = fmt_hm(local) if local.date() == day else f"{fmt_date(local.date(), lang)} {fmt_hm(local)}"
        kind = t("conflict.ad" if c.post.is_ad else "conflict.post", locale=lang)
        lines.append(t(
            "conflict.line", locale=lang, time=when, kind=kind, channel=html.escape(c.channel.title),
            what=_describe(c.post, lang),
        ))
    return "\n".join(lines)
