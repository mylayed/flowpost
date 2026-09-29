"""Giveaways among the people who commented on a post: who entered, drawing the winners and the result post."""
from __future__ import annotations

import html
import logging
import secrets
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Channel, Commenter, Publication
from flowpost.i18n import t
from flowpost.services.slots import fmt_hm, tz_of

log = logging.getLogger(__name__)

WINNER_CHOICES = (1, 3)  # quick buttons; any other count up to MAX_WINNERS is typed in
MAX_WINNERS = 30  # so the announcement stays within one message
MEDALS = ("🥇", "🥈", "🥉")
SUBSCRIBED = {"creator", "administrator", "member"}


async def record(session: AsyncSession, pub: Publication, person: TgUser) -> None:
    """Count `person`'s comment on `pub`; each person enters its giveaway once, however much they write."""
    entrant = await session.scalar(
        select(Commenter).where(Commenter.publication_id == pub.id, Commenter.user_tg_id == person.id)
    )
    if entrant is not None:
        entrant.comments += 1
        entrant.name, entrant.username = person.full_name[:128], person.username
        return
    try:
        async with session.begin_nested():
            session.add(Commenter(publication_id=pub.id, user_tg_id=person.id, name=person.full_name[:128],
                                  username=person.username))
    except IntegrityError:  # their other comment, handled at the same moment, got there first
        pass


async def entrants(session: AsyncSession, pub_id: int) -> list[Commenter]:
    return list(await session.scalars(
        select(Commenter).where(Commenter.publication_id == pub_id).order_by(Commenter.first_at, Commenter.id)
    ))


async def _subscribed(bot: Bot, channel: Channel, user_tg_id: int) -> bool:
    try:
        member = await bot.get_chat_member(channel.chat_id, user_tg_id)
    except TelegramAPIError as e:
        log.info("giveaway membership check failed in channel %s: %s", channel.id, e)
        return False
    status = str(getattr(member.status, "value", member.status))
    return status in SUBSCRIBED or (status == "restricted" and bool(getattr(member, "is_member", False)))


async def draw(
    bot: Bot, channel: Channel, pool: list[Commenter], count: int, *, subscribers_only: bool,
    exclude: set[int] = frozenset(),
) -> list[Commenter]:
    """Up to `count` winners picked uniformly at random (a CSPRNG); with `subscribers_only` whoever has left
    the channel is passed over for the next one in the draw."""
    candidates = [c for c in pool if c.user_tg_id not in exclude]
    secrets.SystemRandom().shuffle(candidates)
    winners: list[Commenter] = []
    for candidate in candidates:
        if len(winners) >= count:
            break
        if subscribers_only and not await _subscribed(bot, channel, candidate.user_tg_id):
            continue
        winners.append(candidate)
    return winners


def mention(entrant: Commenter) -> str:
    name = html.escape(entrant.name or (f"@{entrant.username}" if entrant.username else str(entrant.user_tg_id)))
    link = f'<a href="tg://user?id={entrant.user_tg_id}">{name}</a>'
    return f"{link} (@{html.escape(entrant.username)})" if entrant.username else link


def result_html(winners: list[Commenter], total: int, post_url: str | None, at: datetime, tz: str) -> str:
    """The announcement to publish in the channel."""
    local = at.astimezone(tz_of(tz))
    post = f'<a href="{html.escape(post_url)}">{t("gw.res_post")}</a>' if post_url else t("gw.res_post")
    lines = [
        t("gw.res_title"), "",
        t("gw.res_intro_one" if len(winners) == 1 else "gw.res_intro_many", total=total, post=post), "",
    ]
    rows = [f"{MEDALS[i] if i < len(MEDALS) else f'{i + 1}.'} <b>{mention(w)}</b>" for i, w in enumerate(winners)]
    lines += ["<blockquote>" + "\n".join(rows) + "</blockquote>", ""]
    lines += [t("gw.res_congrats"), "", t("gw.res_footer", date=local.strftime("%d.%m.%Y"), time=fmt_hm(local))]
    return "\n".join(lines)
