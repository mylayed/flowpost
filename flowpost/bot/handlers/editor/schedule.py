"""Editor → «Відкласти»: date switcher, 5-minute slots, typed "ГГ:ХХ" time, confirmation."""
from __future__ import annotations

import html
from datetime import date

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.view import load_editor_post, post_from_callback, show_panel
from flowpost.bot.keyboards.common import btn, markup
from flowpost.bot.keyboards.editor import schedule_kb
from flowpost.bot.states import Editor
from flowpost.db.models import Post, User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.db.repo import publications as pubs_repo
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services import analytics
from flowpost.services.duplicates import find_duplicates, warning_lines
from flowpost.services.html_sanitize import snippet
from flowpost.services.parsing import ParseError, parse_time
from flowpost.services.posts import channel_link_html, part_icon, part_preview_text, post_is_empty
from flowpost.services.slots import (
    WEEKDAYS,
    day_bounds_utc,
    fmt_date,
    fmt_hm,
    generate_slots,
    is_future,
    local_now,
    to_utc,
    tz_of,
)
from flowpost.services.smart_time import SlotSuggestion, best_slots

router = Router(name="editor_schedule")


async def day_overview(session: AsyncSession, user: User, day: date, current_post_id: int | None = None) -> list[str]:
    """Lines like '10:30 🖼 Початок тексту…' for everything scheduled on `day`."""
    start, end = day_bounds_utc(day, user.tz)
    pubs = await pubs_repo.pending_between(session, user.id, start, end)
    seen: set[tuple[int, str]] = set()
    lines: list[str] = []
    zone = tz_of(user.tz)
    cache: dict[int, Post | None] = {}
    for pub in pubs:
        hm = fmt_hm(pub.run_at.astimezone(zone))
        if (pub.post_id, hm) in seen:
            continue
        seen.add((pub.post_id, hm))
        if pub.post_id not in cache:
            cache[pub.post_id] = await posts_repo.get_post(session, user.id, pub.post_id)
        post = cache[pub.post_id]
        if post is None or not post.parts:
            continue
        first = post.parts[0]
        text = html.escape(snippet(part_preview_text(first), 32)) or t("parts.no_text")
        mark = " ← " + t("sch.this_post") if pub.post_id == current_post_id else ""
        lines.append(f"{hm} {part_icon(first)} {text}{mark}")
    return lines


def _format_suggestions(suggestions: list[SlotSuggestion], lang: str) -> str:
    return " • ".join(f"{WEEKDAYS.get(lang, WEEKDAYS['uk'])[s.weekday]} {s.hour:02d}:00" for s in suggestions)


async def show_schedule(
    bot: Bot, chat_id: int, session: AsyncSession, state: FSMContext, user: User, post: Post,
    day: date | None = None, page: int = 0, *, resend: bool = False,
) -> None:
    now_local = local_now(user.tz)
    today = now_local.date()
    day = max(day or today, today)
    await state.set_state(Editor.schedule)
    await state.update_data(sch_day=day.toordinal())
    overview = await day_overview(session, user, day, post.id)
    slots, has_more = generate_slots(day, now_local, page)
    busy = {line.split(" ", 1)[0] for line in overview}
    suggestions = await best_slots(session, user.id, post.channel_ids, user.tz)
    recommended = {f"{s.hour:02d}:00" for s in suggestions if s.weekday == day.weekday()}
    lines = [t("sch.title"), t("sch.date", date=fmt_date(day, user.lang)), ""]
    if overview:
        lines.append(t("sch.planned"))
        lines += overview
    else:
        lines.append(t("sch.none"))
    if suggestions:
        lines.append("")
        lines.append(t("sch.smart_hint", slots=_format_suggestions(suggestions, user.lang)))
    lines.append("")
    lines.append(t("sch.pick") if slots else t("sch.no_slots"))
    kb = schedule_kb(post.id, day, today, slots, has_more, page, user.lang, busy, recommended)
    await show_panel(bot, chat_id, state, "\n".join(lines), kb, resend=resend)


def _parse_day_value(value: str) -> tuple[date | None, int, str]:
    """Callback values look like '<date ordinal>_<page or HHMM>' (':' is reserved by CallbackData)."""
    first, _, second = value.partition("_")
    day = None
    if first.isdigit():
        try:
            day = date.fromordinal(int(first))
        except (ValueError, OverflowError):
            day = None
    return day, int(second) if second.isdigit() else 0, second


async def ask_confirmation(
    bot: Bot, session: AsyncSession, chat_id: int, state: FSMContext, user: User, post: Post,
    day: date, hour: int, minute: int, *, resend: bool = False,
) -> None:
    value = f"{day.toordinal()}_{hour:02d}{minute:02d}"
    channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
    channels_line = ", ".join(channel_link_html(c) for c in channels)
    text = t(
        "sch.confirm", date=fmt_date(day, user.lang), time=f"{hour:02d}:{minute:02d}",
        n=len(post.targets), channels=channels_line,
    )
    if post.repeat and post.repeat.active:
        text += "\n" + t("sch.confirm_repeat")
    matches = await find_duplicates(session, user.id, post, {c.id: c for c in channels})
    for line in warning_lines(matches, user.tz, user.lang):
        text += "\n" + line
    kb = markup([
        [btn(t("sch.confirm_yes"), Ed(a="schok", p=post.id, v=value))],
        [btn(t("sch.change"), Ed(a="sch", p=post.id, v=f"{day.toordinal()}_0"))],
    ])
    await show_panel(bot, chat_id, state, text, kb, resend=resend)


@router.callback_query(Ed.filter(F.a == "sch"))
async def ed_schedule(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    if post_is_empty(post):
        await cb.answer(t("err.post_empty"), show_alert=True)
        return
    await cb.answer()
    day, page, _ = _parse_day_value(callback_data.v)
    await show_schedule(bot, cb.from_user.id, session, state, user, post, day, page)


@router.callback_query(Ed.filter(F.a == "slot"))
async def ed_slot(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    day, _, hhmm = _parse_day_value(callback_data.v)
    if day is None or len(hhmm) != 4:
        await cb.answer()
        return
    hour, minute = int(hhmm[:2]), int(hhmm[2:])
    from datetime import time as dtime

    if not is_future(day, dtime(hour, minute), user.tz):
        await cb.answer(t("sch.past"), show_alert=True)
        return
    await cb.answer()
    await ask_confirmation(bot, session, cb.from_user.id, state, user, post, day, hour, minute)


@router.message(Editor.schedule, F.text)
async def in_time(message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User) -> None:
    post, _ = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    data = await state.get_data()
    day = date.fromordinal(int(data.get("sch_day") or local_now(user.tz).date().toordinal()))
    try:
        when = parse_time(message.text or "")
    except ParseError:
        await message.answer(t("err.time_format"))
        return
    if not is_future(day, when, user.tz):
        await message.answer(t("sch.past"))
        return
    await ask_confirmation(bot, session, message.chat.id, state, user, post, day, when.hour, when.minute, resend=True)


@router.message(Editor.schedule)
async def in_time_wrong(message: Message) -> None:
    await message.answer(t("err.time_format"))


@router.callback_query(Ed.filter(F.a == "schok"), flags={"paid": True})
async def ed_schedule_confirm(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    day, _, hhmm = _parse_day_value(callback_data.v)
    if day is None or len(hhmm) != 4:
        await cb.answer()
        return
    if post_is_empty(post):
        await cb.answer(t("err.post_empty"), show_alert=True)
        return
    if not post.targets:
        await cb.answer(t("post.no_channels"), show_alert=True)
        return
    from datetime import time as dtime

    when = dtime(int(hhmm[:2]), int(hhmm[2:]))
    run_at = to_utc(day, when, user.tz)
    if run_at <= utcnow():
        await cb.answer(t("sch.past"), show_alert=True)
        return
    await pubs_repo.cancel_pending(session, post.id)
    await pubs_repo.create_publications(session, post, run_at)
    post.status = "scheduled"
    analytics.track(session, user.id, "post_scheduled", post_id=post.id)
    await session.flush()
    await cb.answer(t("sch.done_short"))
    channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
    channels_line = ", ".join(channel_link_html(c) for c in channels)
    text = t(
        "sch.done", date=fmt_date(day, user.lang), time=fmt_hm(when), n=len(post.targets), channels=channels_line,
    )
    await show_panel(bot, cb.from_user.id, state, text, None)
    await state.clear()
