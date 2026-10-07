"""Ad posts: the «top» hours of an ad's format, booked slots and the post an ad answers."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Channel, Post, Publication
from flowpost.services.posts import AD_FORMATS, options_of

MAX_TOP_HOURS = max(top for top, _ in AD_FORMATS.values())
ADVERTISER_MAX = 64
_LINK = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(?:c/(\d+)|([A-Za-z0-9_]{4,}))/(\d+)", re.I)


def is_booking(post: Post) -> bool:
    return post.is_ad and bool(options_of(post).get("ad_booking"))


def format_of(post: Post) -> tuple[int, int] | None:
    """(top hours, feed hours) of the ad's format, or None when it has none."""
    return AD_FORMATS.get(options_of(post).get("ad_format") or 0)


async def top_until(session: AsyncSession, channel_id: int, now: datetime) -> datetime | None:
    """While an ad published in the channel is still in its «top» hours, the moment they end."""
    rows = (await session.execute(
        select(Publication.published_at, Post.options)
        .join(Post, Post.id == Publication.post_id)
        .where(
            Publication.channel_id == channel_id,
            Publication.status == "published",
            Publication.published_at > now - timedelta(hours=MAX_TOP_HOURS),
            Post.is_ad.is_(True),
        )
    )).all()
    ends = [
        published_at + timedelta(hours=AD_FORMATS[(options or {}).get("ad_format")][0])
        for published_at, options in rows
        if published_at is not None and (options or {}).get("ad_format") in AD_FORMATS
    ]
    end = max(ends, default=None)
    return end if end is not None and end > now else None


def looks_like_advertiser(text: str) -> bool:
    """A booking gets either the ad itself or just who's buying it: a short single line is taken for a name."""
    text = (text or "").strip()
    return bool(text) and "\n" not in text and len(text) <= ADVERTISER_MAX and "://" not in text


def parse_post_link(text: str, channels: list[Channel]) -> tuple[Channel, int] | None:
    """The channel among `channels` and the message id a t.me post link points to."""
    m = _LINK.search(text or "")
    if m is None:
        return None
    internal, username, message_id = m.groups()
    for channel in channels:
        if internal and str(channel.chat_id) == f"-100{internal}":
            return channel, int(message_id)
        if username and channel.username and channel.username.lower() == username.lower():
            return channel, int(message_id)
    return None
