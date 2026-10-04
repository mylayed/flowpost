"""Giveaways: among the people who commented on a post, or among whoever tapped the «Беру участь» button under
one — who entered, drawing the winners and the result post."""
from __future__ import annotations

import html
import logging
import secrets
from datetime import datetime
from typing import Protocol, Sequence

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import User as TgUser
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.config import Settings
from flowpost.db.models import Channel, Commenter, Giveaway, GiveawayEntry, Post, Publication, User
from flowpost.db.repo import publications as pubs_repo
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services.billing import entitlements
from flowpost.services.posts import GIVEAWAY_PREFIX, build_markup, part_buttons
from flowpost.services.slots import fmt_hm, tz_of

log = logging.getLogger(__name__)

WINNER_CHOICES = (1, 3)  # quick buttons; any other count up to MAX_WINNERS is typed in
MAX_WINNERS = 30  # so the announcement stays within one message
MEDALS = ("🥇", "🥈", "🥉")
SUBSCRIBED = {"creator", "administrator", "member"}
MAX_BUTTON_TEXT = 40


class Entrant(Protocol):
    """A commenter or someone who tapped the button."""

    user_tg_id: int
    name: str
    username: str | None


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
    bot: Bot, channel: Channel, pool: Sequence[Entrant], count: int, *, subscribers_only: bool,
    exclude: set[int] = frozenset(),
) -> list[Entrant]:
    """Up to `count` winners picked uniformly at random (a CSPRNG); with `subscribers_only` whoever has left
    the channel is passed over for the next one in the draw."""
    candidates = [c for c in pool if c.user_tg_id not in exclude]
    secrets.SystemRandom().shuffle(candidates)
    winners: list[Entrant] = []
    for candidate in candidates:
        if len(winners) >= count:
            break
        if subscribers_only and not await _subscribed(bot, channel, candidate.user_tg_id):
            continue
        winners.append(candidate)
    return winners


def mention(entrant: Entrant) -> str:
    name = html.escape(entrant.name or (f"@{entrant.username}" if entrant.username else str(entrant.user_tg_id)))
    link = f'<a href="tg://user?id={entrant.user_tg_id}">{name}</a>'
    return f"{link} (@{html.escape(entrant.username)})" if entrant.username else link


def result_html(winners: Sequence[Entrant], total: int, post_url: str | None, at: datetime, tz: str) -> str:
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


# ---- giveaways with a «Беру участь» button -----------------------------------------------------

async def create(session: AsyncSession, channel: Channel, button_text: str) -> Giveaway:
    gw = Giveaway(channel_id=channel.id, button_text=button_text.strip()[:MAX_BUTTON_TEXT], subscribers_only=True,
                  is_open=True, entries=0, shown=0)
    session.add(gw)
    await session.flush()
    return gw


def entry_button(gw: Giveaway, settings: Settings, bot_username: str | None) -> dict:
    """The button under the giveaway post. With a Mini App registered for giveaways it opens it (a channel can't
    carry web_app buttons, only a t.me link to the app); otherwise a tap is answered with a pop-up."""
    if settings.webapp_url and settings.giveaway_app and bot_username:
        url = f"https://t.me/{bot_username}/{settings.giveaway_app}?startapp=gw{gw.id}"
        return {"text": gw.button_text, "url": url, "giveaway": gw.id}
    return {"text": gw.button_text, "callback": f"{GIVEAWAY_PREFIX}{gw.id}", "giveaway": gw.id}


def parse_start(param: str | None) -> int | None:
    """The giveaway id in a Mini App start parameter ("gw42")."""
    raw = (param or "").removeprefix("gw")
    return int(raw) if raw.isdigit() else None


async def join(
    bot: Bot, session: AsyncSession, gw_id: int, person: TgUser,
) -> tuple[str, Giveaway | None, Channel | None]:
    """Enter `person` into the giveaway: "joined", "already", "subscribe" (members only, and they aren't one),
    "closed" or "gone"."""
    gw = await session.get(Giveaway, gw_id)
    channel = await session.get(Channel, gw.channel_id) if gw is not None else None
    if gw is None or channel is None or gw.post_id is None:
        return "gone", gw, channel
    entered = await session.scalar(
        select(GiveawayEntry.id).where(GiveawayEntry.giveaway_id == gw.id, GiveawayEntry.user_tg_id == person.id)
    )
    if entered is not None:
        return "already", gw, channel
    if not gw.is_open:
        return "closed", gw, channel
    if gw.subscribers_only and not await _subscribed(bot, channel, person.id):
        return "subscribe", gw, channel
    try:
        async with session.begin_nested():
            session.add(GiveawayEntry(giveaway_id=gw.id, user_tg_id=person.id, name=(person.full_name or "")[:128],
                                      username=person.username))
    except IntegrityError:  # a second tap handled at the same moment
        return "already", gw, channel
    await session.execute(update(Giveaway).where(Giveaway.id == gw.id).values(entries=Giveaway.entries + 1))
    await session.refresh(gw)
    return "joined", gw, channel


async def button_entrants(session: AsyncSession, gw_id: int) -> list[GiveawayEntry]:
    return list(await session.scalars(
        select(GiveawayEntry).where(GiveawayEntry.giveaway_id == gw_id)
        .order_by(GiveawayEntry.first_at, GiveawayEntry.id)
    ))


def counted(rows: list[list[dict]], gw: Giveaway) -> list[list[dict]]:
    """`rows` with the giveaway's button showing how many have entered: «Беру участь! (49)»."""
    label = f"{gw.button_text} ({gw.entries})" if gw.entries else gw.button_text
    return [[{**b, "text": label} if b.get("giveaway") == gw.id else b for b in row] for row in rows]


async def refresh_counter(bot: Bot, session: AsyncSession, gw: Giveaway) -> None:
    """Write the number of entrants onto the button of every published copy of the giveaway post."""
    shown = gw.entries
    post = await session.get(Post, gw.post_id) if gw.post_id else None
    if post is not None:
        owner = await session.get(User, post.owner_id)
        lang = owner.lang if owner else "uk"
        for pub in await pubs_repo.published_for_post(session, post.id):
            channel = await session.get(Channel, pub.channel_id)
            if channel is None:
                continue
            hidden = await entitlements.extras_allowed(session, [channel], utcnow())
            for idx, rec in enumerate((pub.message_ids or {}).get("parts", [])[:len(post.parts)]):
                rows = part_buttons(post, idx, lang, hidden=hidden)
                if not rec.get("markup_msg") or not any(b.get("giveaway") == gw.id for row in rows for b in row):
                    continue
                try:
                    await bot.edit_message_reply_markup(
                        chat_id=channel.chat_id, message_id=rec["markup_msg"],
                        reply_markup=build_markup(counted(rows, gw)),
                    )
                except TelegramBadRequest as e:
                    if "not modified" not in str(e):
                        log.info("giveaway %s counter not updated: %s", gw.id, e)
                except TelegramAPIError as e:
                    log.info("giveaway %s counter not updated: %s", gw.id, e)
    gw.shown = shown


async def refresh_counters(bot: Bot, session: AsyncSession, limit: int = 20) -> None:
    """Giveaways whose button shows an outdated number of entrants. The worker calls this every few seconds, so
    a burst of taps costs one edit of the channel post, not one per tap."""
    stale = (await session.scalars(
        select(Giveaway).where(Giveaway.entries != Giveaway.shown, Giveaway.post_id.is_not(None)).limit(limit)
    )).all()
    for gw in stale:
        await refresh_counter(bot, session, gw)
