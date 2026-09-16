"""«Контент-план»: day-by-day view of scheduled posts across all channels."""
from __future__ import annotations

import html
from datetime import date

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Cp
from flowpost.bot.handlers.editor.publish import publish_now
from flowpost.bot.handlers.editor.schedule import show_schedule
from flowpost.bot.handlers.editor.view import fmt_interval, open_editor
from flowpost.bot.keyboards.common import btn, markup, page_nav, paged
from flowpost.db.models import Channel, User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.db.repo import publications as pubs_repo
from flowpost.i18n import t
from flowpost.services.html_sanitize import snippet
from flowpost.services.posts import part_icon, post_is_empty
from flowpost.services.publisher import Publisher
from flowpost.services.slots import day_bounds_utc, fmt_date, fmt_hm, local_now, tz_of
from flowpost.services.worker import Worker

router = Router(name="content_plan")


async def channel_picker_view(
    channels: list[Channel], per_page: int = 20, page: int = 0
) -> tuple[str, InlineKeyboardMarkup]:
    page, pages = paged(page, len(channels), per_page)
    rows = [
        [btn(("📢 " if c.kind == "channel" else "👥 ") + c.title, Cp(a="day", c=c.id))]
        for c in channels[page * per_page:(page + 1) * per_page]
    ]
    if pages > 1:
        rows.append(page_nav(page, pages, lambda n: Cp(a="channels", pg=n), Cp(a="noop")))
    rows.append([btn(t("plan.all_channels"), Cp(a="day", c=0))])
    return t("plan.pick_channel"), markup(rows)


async def plan_view(
    session: AsyncSession, user: User, day: date | None = None, mode: str = "s", channel_id: int = 0,
    *, multi: bool = False,
) -> tuple[str, InlineKeyboardMarkup]:
    today = local_now(user.tz).date()
    day = max(day or today, today)
    ordinal = day.toordinal()
    start, end = day_bounds_utc(day, user.tz)
    published = mode == "p"
    channel_ids = [channel_id] if channel_id else None
    pubs = await (pubs_repo.published_between if published else pubs_repo.pending_between)(
        session, user.id, start, end, channel_ids=channel_ids
    )
    zone = tz_of(user.tz)
    c = channel_id

    rows = [
        [
            btn("◀️", Cp(a="day", d=ordinal - 1, m=mode, c=c)) if day > today else btn("·", Cp(a="noop")),
            btn(fmt_date(day, user.lang), Cp(a="noop")),
            btn("▶️", Cp(a="day", d=ordinal + 1, m=mode, c=c)),
        ],
        [
            btn(t("plan.tab_scheduled"), Cp(a="day", d=ordinal, m="s", c=c)),
            btn(t("plan.tab_published"), Cp(a="day", d=ordinal, m="p", c=c)),
        ],
    ]
    if multi:
        rows.append([btn(t("plan.channels_btn"), Cp(a="channels", d=ordinal, m=mode))])
    lines = [t("plan.title"), t("sch.date", date=fmt_date(day, user.lang)), ""]
    seen: set[int] = set()
    for pub in pubs:
        if pub.post_id in seen:
            continue
        seen.add(pub.post_id)
        post = await posts_repo.get_post(session, user.id, pub.post_id)
        if post is None or not post.parts:
            continue
        first = post.parts[0]
        when = pub.published_at if published else pub.run_at
        label = f"{fmt_hm(when.astimezone(zone))} {part_icon(first)} {snippet(first.text_html, 30) or t('parts.no_text')}"
        if not published and pub.status == "paused":
            label = "⏸ " + label
        rows.append([btn(label, Cp(a="post", d=ordinal, id=post.id, m=mode, c=c))])
    lines.append((t("plan.count_published", n=len(seen)) if seen else t("plan.empty_published")) if published
                 else (t("plan.count", n=len(seen)) if seen else t("plan.empty")))
    rows.append([btn(t("plan.new_post"), Cp(a="new"))])
    return "\n".join(lines), markup(rows)


async def send_plan(message: Message, session: AsyncSession, user: User) -> None:
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    if len(channels) > 1:
        text, kb = await channel_picker_view(channels, user.channels_per_page)
        await message.answer(text, reply_markup=kb)
        return
    channel_id = channels[0].id if channels else 0
    text, kb = await plan_view(session, user, channel_id=channel_id)
    await message.answer(text, reply_markup=kb)


async def _edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None) -> None:
    if cb.message is None:
        return
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await cb.message.answer(text, reply_markup=kb)


@router.callback_query(Cp.filter(F.a == "noop"))
async def cp_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(Cp.filter(F.a == "day"))
async def cp_day(cb: CallbackQuery, callback_data: Cp, session: AsyncSession, user: User) -> None:
    await cb.answer()
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    day = date.fromordinal(callback_data.d) if callback_data.d else None
    await _edit(cb, *await plan_view(
        session, user, day, callback_data.m, callback_data.c, multi=len(channels) > 1,
    ))


@router.callback_query(Cp.filter(F.a == "channels"))
async def cp_channels(cb: CallbackQuery, callback_data: Cp, session: AsyncSession, user: User) -> None:
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    await cb.answer()
    await _edit(cb, *await channel_picker_view(channels, user.channels_per_page, callback_data.pg))


@router.callback_query(Cp.filter(F.a == "post"))
async def cp_post(cb: CallbackQuery, callback_data: Cp, session: AsyncSession, user: User) -> None:
    post = await posts_repo.get_post(session, user.id, callback_data.id)
    if post is None:
        await cb.answer(t("err.post_not_found"), show_alert=True)
        return
    await cb.answer()
    published = callback_data.m == "p"
    zone = tz_of(user.tz)
    lines = [t("plan.post_title_published") if published else t("plan.post_title"), ""]
    first = post.parts[0]
    lines.append(f"{part_icon(first)} {html.escape(snippet(first.text_html, 120)) or t('parts.no_text')}")
    if len(post.parts) > 1:
        lines.append(t("ed.part", n=1, total=len(post.parts)))
    lines.append("")
    start, end = day_bounds_utc(date.fromordinal(callback_data.d), user.tz)
    channel_ids = [callback_data.c] if callback_data.c else None
    pubs = await (pubs_repo.published_between if published else pubs_repo.pending_between)(
        session, user.id, start, end, channel_ids=channel_ids
    )
    icon = "✅" if published else "📡"
    for pub in pubs:
        if pub.post_id != post.id:
            continue
        channel = await session.get(Channel, pub.channel_id)
        local = (pub.published_at if published else pub.run_at).astimezone(zone)
        lines.append(f"{icon} {html.escape(channel.title if channel else '?')} — {fmt_date(local.date(), user.lang)} {fmt_hm(local)}")
    if not published and post.repeat and post.repeat.active:
        lines.append(t("ed.sum_repeat", interval=fmt_interval(post.repeat.interval_minutes)))
    p, d, m, c = post.id, callback_data.d, callback_data.m, callback_data.c
    if published:
        rows = [[btn(t("plan.edit"), Cp(a="edit", d=d, id=p, m=m, c=c))]]
    else:
        rows = [
            [btn(t("plan.edit"), Cp(a="edit", d=d, id=p, m=m, c=c)), btn(t("plan.move"), Cp(a="move", d=d, id=p, m=m, c=c))],
            [btn(t("plan.now"), Cp(a="now", d=d, id=p, m=m, c=c))],
            [btn(t("plan.drop"), Cp(a="drop", d=d, id=p, m=m, c=c))],
        ]
    rows.append([btn(t("btn.back"), Cp(a="day", d=d, m=m, c=c))])
    await _edit(cb, "\n".join(lines), markup(rows))


@router.callback_query(Cp.filter(F.a.in_({"edit", "move"})))
async def cp_edit(
    cb: CallbackQuery, callback_data: Cp, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post = await posts_repo.get_post(session, user.id, callback_data.id)
    if post is None:
        await cb.answer(t("err.post_not_found"), show_alert=True)
        return
    await cb.answer()
    await open_editor(bot, cb.from_user.id, session, state, user, post, publisher)
    if callback_data.a == "move":
        await show_schedule(bot, cb.from_user.id, session, state, user, post, date.fromordinal(callback_data.d))


@router.callback_query(Cp.filter(F.a == "now"), flags={"publish": True})
async def cp_publish_now(
    cb: CallbackQuery, callback_data: Cp, session: AsyncSession, user: User, worker: Worker
) -> None:
    post = await posts_repo.get_post(session, user.id, callback_data.id)
    if post is None or post_is_empty(post) or not post.targets:
        await cb.answer(t("err.post_not_found"), show_alert=True)
        return
    await cb.answer(t("pub.working"))
    report = await publish_now(session, worker, post)
    await _edit(cb, report, markup([[btn(t("btn.back"), Cp(a="day", d=callback_data.d, c=callback_data.c))]]))


@router.callback_query(Cp.filter(F.a.in_({"drop", "dropok"})))
async def cp_drop(cb: CallbackQuery, callback_data: Cp, session: AsyncSession, user: User) -> None:
    post = await posts_repo.get_post(session, user.id, callback_data.id)
    if post is None:
        await cb.answer(t("err.post_not_found"), show_alert=True)
        return
    if callback_data.a == "drop":
        await cb.answer()
        kb = markup([
            [btn(t("plan.drop_yes"), Cp(a="dropok", d=callback_data.d, id=post.id, c=callback_data.c))],
            [btn(t("btn.back"), Cp(a="post", d=callback_data.d, id=post.id, m=callback_data.m, c=callback_data.c))],
        ])
        await _edit(cb, t("plan.drop_confirm"), kb)
        return
    await pubs_repo.cancel_pending(session, post.id)
    if post.repeat is not None:
        post.repeat.active = False
    await pubs_repo.refresh_post_status(session, post)
    await session.flush()
    await cb.answer(t("plan.dropped"))
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    await _edit(cb, *await plan_view(
        session, user, date.fromordinal(callback_data.d), channel_id=callback_data.c, multi=len(channels) > 1,
    ))


@router.callback_query(Cp.filter(F.a == "new"))
async def cp_new(
    cb: CallbackQuery, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher
) -> None:
    from flowpost.bot.handlers.create_post import start_post

    await cb.answer()
    if cb.message is not None:
        await start_post(cb.message, bot, session, state, user, publisher)
