"""Growing a channel: tracked invite links (who came from which ad) and join requests the bot approves and greets."""
from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Channel, InviteJoin, InviteLink, JoinRequest
from flowpost.i18n import t

log = logging.getLogger(__name__)

APPROVE_CHOICES = ("off", "now", "10", "60", "1440")  # "<n>" = approve after n minutes
MAX_WELCOME = 2000
MAX_LINKS = 50


def join_settings(raw: dict | None) -> dict:
    return {"approve": "off", "welcome": False, "welcome_html": "", "link": "", **(raw or {})}


def approve_delay(settings: dict) -> timedelta | None:
    """How long to wait before approving a request; None = the bot doesn't approve at all."""
    value = settings.get("approve", "off")
    if value == "now":
        return timedelta(0)
    if isinstance(value, str) and value.isdigit():
        return timedelta(minutes=int(value))
    return None


def handles_requests(channel: Channel) -> bool:
    s = join_settings(channel.join_settings)
    return approve_delay(s) is not None or bool(s["welcome"])


@dataclass
class LinkStats:
    link: InviteLink
    joined: int
    left: int

    @property
    def stayed(self) -> int:
        return self.joined - self.left

    @property
    def cost_per_member(self) -> float | None:
        return self.link.cost / self.joined if self.link.cost and self.joined else None


async def link_stats(session: AsyncSession, links: list[InviteLink]) -> list[LinkStats]:
    if not links:
        return []
    rows = (await session.execute(
        select(InviteJoin.link_id, func.count(InviteJoin.id), func.count(InviteJoin.left_at))
        .where(InviteJoin.link_id.in_([link.id for link in links]))
        .group_by(InviteJoin.link_id)
    )).all()
    counts = {link_id: (joined, left) for link_id, joined, left in rows}
    return [LinkStats(link, *counts.get(link.id, (0, 0))) for link in links]


async def channel_links(session: AsyncSession, channel_id: int) -> list[InviteLink]:
    return list((await session.scalars(
        select(InviteLink).where(InviteLink.channel_id == channel_id, InviteLink.revoked.is_(False))
        .order_by(InviteLink.id.desc())
    )).all())


async def find_link(session: AsyncSession, chat_id: int, url: str | None) -> InviteLink | None:
    """The tracked link `url` of any channel connected under `chat_id`."""
    if not url:
        return None
    return await session.scalar(
        select(InviteLink).join(Channel, Channel.id == InviteLink.channel_id)
        .where(Channel.chat_id == chat_id, InviteLink.url == url)
        .limit(1)
    )


async def record_join(session: AsyncSession, link: InviteLink, user_tg_id: int, now: datetime) -> None:
    """Count a join once per person per link; coming back after leaving counts as staying again."""
    row = await session.scalar(
        select(InviteJoin).where(InviteJoin.link_id == link.id, InviteJoin.user_tg_id == user_tg_id)
    )
    if row is None:
        session.add(InviteJoin(link_id=link.id, user_tg_id=user_tg_id, joined_at=now))
    else:
        row.left_at = None
    await session.flush()


async def record_leave(session: AsyncSession, chat_id: int, user_tg_id: int, now: datetime) -> None:
    rows = (await session.scalars(
        select(InviteJoin)
        .join(InviteLink, InviteLink.id == InviteJoin.link_id)
        .join(Channel, Channel.id == InviteLink.channel_id)
        .where(Channel.chat_id == chat_id, InviteJoin.user_tg_id == user_tg_id, InviteJoin.left_at.is_(None))
    )).all()
    for row in rows:
        row.left_at = now
    await session.flush()


async def joins_since(session: AsyncSession, channel_id: int, since: datetime) -> list[tuple[str, int]]:
    """Joins per tracked link since `since`, most first — for the weekly report."""
    rows = (await session.execute(
        select(InviteLink.name, func.count(InviteJoin.id))
        .join(InviteJoin, InviteJoin.link_id == InviteLink.id)
        .where(InviteLink.channel_id == channel_id, InviteJoin.joined_at >= since)
        .group_by(InviteLink.name)
        .order_by(func.count(InviteJoin.id).desc())
    )).all()
    return [(name, n) for name, n in rows]


async def approve_request(bot: Bot, session: AsyncSession, channel: Channel, row: JoinRequest, now: datetime) -> bool:
    """Let the person in; a request someone already handled (approved, declined, withdrawn) just stops waiting."""
    row.approve_at = None
    try:
        await bot.approve_chat_join_request(channel.chat_id, row.user_tg_id)
    except TelegramBadRequest as e:
        log.info("join request of %s in %s not approved: %s", row.user_tg_id, channel.chat_id, e)
        return False
    except TelegramAPIError as e:
        log.warning("approve_chat_join_request failed in %s: %s", channel.chat_id, e)
        return False
    row.approved_at = now
    link = await find_link(session, channel.chat_id, row.invite_url)
    if link is not None:
        await record_join(session, link, row.user_tg_id, now)
    return True


def welcome_text(channel: Channel, first_name: str | None, lang: str) -> str:
    template = join_settings(channel.join_settings)["welcome_html"] or t("jr.welcome_default", locale=lang)
    return (
        template.replace("{name}", html.escape(first_name or ""))
        .replace("{title}", html.escape(channel.title or ""))
    )


async def queue_request(
    session: AsyncSession, channel: Channel, user_tg_id: int, invite_url: str | None, now: datetime,
) -> JoinRequest:
    """Remember a join request and when to approve it (None = the owner approves it themselves)."""
    delay = approve_delay(join_settings(channel.join_settings))
    row = await session.scalar(
        select(JoinRequest).where(JoinRequest.channel_id == channel.id, JoinRequest.user_tg_id == user_tg_id)
    )
    if row is None:
        row = JoinRequest(channel_id=channel.id, user_tg_id=user_tg_id)
        session.add(row)
    row.invite_url = invite_url
    row.requested_at = now
    row.approved_at = None
    row.approve_at = now + delay if delay is not None else None
    await session.flush()
    return row
