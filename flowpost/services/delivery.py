"""Delivering a single publication into its channel: send, pin, schedule deletion and repeats."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Channel, Post, Publication, User
from flowpost.db.repo import posts as posts_repo
from flowpost.services import analytics
from flowpost.services.posts import message_link, options_of, post_is_empty
from flowpost.services.publisher import Publisher

log = logging.getLogger(__name__)


class DeliveryError(Exception):
    """Non-retryable problem with the publication itself (i18n key)."""

    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


@dataclass
class DeliveryOutcome:
    ok: bool
    channel_title: str = ""
    link: str | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


def publication_message_ids(pub: Publication) -> list[int]:
    return [i for part in (pub.message_ids or {}).get("parts", []) for i in part.get("ids", [])]


def reactions_total(pub: Publication) -> int:
    return sum(count for per_message in (pub.reactions or {}).values() for count in per_message.values())


def engagement_score(pub: Publication) -> int:
    return reactions_total(pub) + (pub.comments_count or 0)


async def delete_publication_messages(bot: Bot, channel: Channel, pub: Publication) -> None:
    ids = publication_message_ids(pub)
    for start in range(0, len(ids), 100):
        try:
            await bot.delete_messages(channel.chat_id, ids[start:start + 100])
        except TelegramAPIError as e:
            log.warning("delete_messages failed for pub %s: %s", pub.id, e)
    pub.deleted = True
    pub.delete_at = None
    pub.unpin_at = None


async def _delete_previous_repeat(session: AsyncSession, bot: Bot, pub: Publication, channel: Channel) -> None:
    prev = await session.scalar(
        select(Publication)
        .where(
            Publication.post_id == pub.post_id,
            Publication.channel_id == pub.channel_id,
            Publication.status == "published",
            Publication.deleted.is_(False),
            Publication.repeat_index < pub.repeat_index,
        )
        .order_by(Publication.repeat_index.desc())
        .limit(1)
    )
    if prev is not None:
        await delete_publication_messages(bot, channel, prev)


async def _schedule_repeat(session: AsyncSession, post: Post, pub: Publication, now: datetime) -> None:
    rule = post.repeat
    if rule is None or not rule.active:
        return
    next_index = pub.repeat_index + 1
    if rule.remaining_count is not None and next_index > rule.remaining_count:
        return
    interval = timedelta(minutes=rule.interval_minutes)
    next_run = pub.run_at + interval
    if next_run <= now:
        next_run = now + interval
    if rule.until is not None and next_run > rule.until:
        return
    exists = await session.scalar(
        select(Publication.id).where(
            Publication.post_id == post.id,
            Publication.channel_id == pub.channel_id,
            Publication.repeat_index == next_index,
            Publication.status.in_(("pending", "paused", "publishing", "published")),
        )
    )
    if exists:
        return
    session.add(
        Publication(
            post_id=post.id,
            channel_id=pub.channel_id,
            owner_id=pub.owner_id,
            run_at=next_run,
            status="pending",
            repeat_index=next_index,
            notify=True,
            message_ids={},
        )
    )


async def deliver_publication(
    session: AsyncSession, publisher: Publisher, pub: Publication, *, now: datetime
) -> DeliveryOutcome:
    """Send `pub`. Telegram exceptions propagate so the caller can decide about retries."""
    owner = await session.get(User, pub.owner_id)
    post = await posts_repo.get_post(session, pub.owner_id, pub.post_id)
    channel = await session.get(Channel, pub.channel_id)
    if owner is None or post is None or channel is None:
        raise DeliveryError("err.pub_missing")
    if not channel.is_active:
        raise DeliveryError("err.channel_inactive")
    if post_is_empty(post):
        raise DeliveryError("err.post_empty")

    opts = options_of(post)
    bot = publisher.bot
    if pub.repeat_index > 0 and post.repeat is not None and post.repeat.delete_previous:
        await _delete_previous_repeat(session, bot, pub, channel)

    result = await publisher.publish_post(post, channel, owner.lang)
    outcome = DeliveryOutcome(ok=True, channel_title=channel.title, warnings=list(result.warnings))

    pub.message_ids = {"parts": [p.to_dict() for p in result.parts]}
    pub.status = "published"
    pub.published_at = now
    pub.last_error = None
    first_id = result.parts[0].ids[0] if result.parts and result.parts[0].ids else None
    outcome.link = message_link(channel, first_id) if first_id else None

    if opts.get("pin") and first_id:
        try:
            await bot.pin_chat_message(channel.chat_id, first_id, disable_notification=True)
            if opts.get("pin_hours"):
                pub.unpin_at = now + timedelta(hours=float(opts["pin_hours"]))
        except TelegramAPIError as e:
            log.warning("pin failed for pub %s: %s", pub.id, e)
            outcome.warnings.append("warn.pin_failed")
    if opts.get("auto_delete_hours"):
        pub.delete_at = now + timedelta(hours=float(opts["auto_delete_hours"]))

    post.published_at = now
    analytics.track(session, owner.id, "post_published", channel_id=channel.id, post_id=post.id)
    await _schedule_repeat(session, post, pub, now)
    return outcome
