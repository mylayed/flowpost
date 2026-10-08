"""«Контент-план»: day-by-day view of scheduled posts across all channels."""
from __future__ import annotations

import html
from contextlib import suppress
from datetime import date

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputRichMessage, Message, WebAppInfo,
)
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Cp
from flowpost.bot.handlers.editor.publish import publish_now
from flowpost.bot.handlers.editor.schedule import show_schedule
from flowpost.bot.handlers.editor.view import NO_PREVIEW, fmt_interval, open_editor
from flowpost.bot.keyboards.common import btn, markup, page_nav, paged
from flowpost.config import Settings
from flowpost.db.models import Channel, Post, User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.db.repo import publications as pubs_repo
from flowpost.i18n import t
from flowpost.services.html_sanitize import snippet
from flowpost.services import ads
from flowpost.services.posts import channel_link_html, part_icon, part_preview_text, post_is_empty
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


PLAN_ROWS_LIMIT = 100  # rich messages allow 500 blocks; a day never needs more than this


def _row(post: Post, when: str, status: str, open_cb: Cp, channel: Channel | None) -> str:
    """A table row: «⏳ 12:00» | «🖼 НОРМ ЧИ СТРЬОМ…» | «Відкрити» on the right; an ad gets 💰 and «Реклама»."""
    first = post.parts[0]
    title = html.escape(snippet(part_preview_text(first), 60)) or t("parts.no_text")
    if post.is_ad:
        what = f"💰 <b>{t('cp.ad_label')}</b> · <i>{title}</i>"
    else:
        what = f"{part_icon(first)} <i>{title}</i>"
    if channel is not None:
        what += f"<br>📢 {html.escape(channel.title)}"
    button = f'<tg-button type="callback_data" style="link" data="{open_cb.pack()}">{t("cp.open")}</tg-button>'
    return (
        f'<tr><td valign="top">{status}&nbsp;<b>{when}</b></td><td align="left" valign="top">{what}</td>'
        f'<td align="right" valign="middle">{button}</td></tr>'
    )


async def plan_view(
    session: AsyncSession, user: User, day: date | None = None, mode: str = "s", channel_id: int = 0,
    *, multi: bool = False, settings: Settings | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """The day's posts as rich HTML (a table: time, post, «Відкрити») and the navigation keyboard."""
    today = local_now(user.tz).date()
    day = max(day or today, today) if mode != "p" else (day or today)
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
            btn("◀️", Cp(a="day", d=ordinal - 1, m=mode, c=c)) if day > today or published else btn("·", Cp(a="noop")),
            btn(fmt_date(day, user.lang), Cp(a="noop")),
            btn("▶️", Cp(a="day", d=ordinal + 1, m=mode, c=c)) if day < today or not published else btn("·", Cp(a="noop")),
        ],
        [
            btn(("• " if not published else "") + t("plan.tab_scheduled"), Cp(a="day", d=ordinal, m="s", c=c)),
            btn(("• " if published else "") + t("plan.tab_published"), Cp(a="day", d=ordinal, m="p", c=c)),
        ],
    ]
    if multi:
        rows.append([btn(t("plan.channels_btn"), Cp(a="channels", d=ordinal, m=mode))])

    channel = await session.get(Channel, channel_id) if channel_id else None
    header = f"📢 <i>{channel_link_html(channel)}</i>" if channel is not None else t("plan.all_channels")
    parts = [f"<p>{header}<br>{t('cp.title')}</p>"]

    entries: list[str] = []
    seen: set[int] = set()
    for pub in pubs:
        if pub.post_id in seen:
            continue
        post = await posts_repo.get_post(session, user.id, pub.post_id)
        if post is None or not post.parts:
            continue
        seen.add(pub.post_id)
        when = fmt_hm((pub.published_at if published else pub.run_at).astimezone(zone))
        if published:
            status = "✅"
        elif pub.status == "paused":
            status = "⏸"
        else:
            status = "🔐" if post.is_ad else "⏳"
        other = None if channel_id else await session.get(Channel, pub.channel_id)
        entries.append(_row(post, when, status, Cp(a="post", d=ordinal, id=post.id, m=mode, c=c), other))

    if entries:
        parts.append(f"<p>{t('cp.hint')}</p>")
        head = f'<tr><th colspan="3" align="left">{fmt_date(day, user.lang)} {day.year}</th></tr>'
        parts.append("<table striped>" + head + "".join(entries[:PLAN_ROWS_LIMIT]) + "</table>")
        if len(entries) > PLAN_ROWS_LIMIT:
            parts.append(f"<p>{t('cp.more', n=len(entries) - PLAN_ROWS_LIMIT)}</p>")
    else:
        parts.append(f"<p>{t('plan.empty_published') if published else t('plan.empty')}</p>")
    url = settings.calendar_url(channel_id) if settings is not None else None
    if url:
        rows.append([InlineKeyboardButton(text=t("plan.calendar"), web_app=WebAppInfo(url=url))])
    rows.append([btn(t("plan.new_post"), Cp(a="new"))])
    return "".join(parts), markup(rows)


def _rich(body: str) -> InputRichMessage:
    return InputRichMessage(html=body, skip_entity_detection=True)


async def send_plan(message: Message, session: AsyncSession, user: User, settings: Settings) -> None:
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    if len(channels) > 1:
        text, kb = await channel_picker_view(channels, user.channels_per_page)
        await message.answer(text, reply_markup=kb)
        return
    channel_id = channels[0].id if channels else 0
    body, kb = await plan_view(session, user, channel_id=channel_id, settings=settings)
    await message.bot.send_rich_message(message.chat.id, _rich(body), reply_markup=kb)


async def _show_plan(cb: CallbackQuery, bot: Bot, body: str, kb: InlineKeyboardMarkup) -> None:
    """Puts the plan in place of the pressed screen: edited in place if that's already a plan, else sent anew."""
    msg = cb.message
    if msg is not None and getattr(msg, "rich_message", None) is not None:
        try:
            await bot.edit_message_text(
                chat_id=msg.chat.id, message_id=msg.message_id, rich_message=_rich(body), reply_markup=kb
            )
            return
        except TelegramBadRequest as e:
            if "not modified" in str(e):
                return
    if msg is not None:
        with suppress(TelegramBadRequest):
            await msg.delete()
    await bot.send_rich_message(cb.from_user.id, _rich(body), reply_markup=kb)


async def _edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None) -> None:
    if cb.message is None:
        return
    if getattr(cb.message, "text", None) is None:
        # the plan (a rich message) or a card with a media preview can't be edited into a text screen
        with suppress(TelegramBadRequest):
            await cb.message.delete()
        await cb.message.answer(text, reply_markup=kb, link_preview_options=NO_PREVIEW)
        return
    try:
        await cb.message.edit_text(text, reply_markup=kb, link_preview_options=NO_PREVIEW)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await cb.message.answer(text, reply_markup=kb, link_preview_options=NO_PREVIEW)


@router.callback_query(Cp.filter(F.a == "noop"))
async def cp_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(Cp.filter(F.a == "day"))
async def cp_day(
    cb: CallbackQuery, callback_data: Cp, bot: Bot, session: AsyncSession, user: User, settings: Settings
) -> None:
    await cb.answer()
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    day = date.fromordinal(callback_data.d) if callback_data.d else None
    await _show_plan(cb, bot, *await plan_view(
        session, user, day, callback_data.m, callback_data.c, multi=len(channels) > 1, settings=settings,
    ))


@router.callback_query(Cp.filter(F.a == "channels"))
async def cp_channels(cb: CallbackQuery, callback_data: Cp, session: AsyncSession, user: User) -> None:
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    await cb.answer()
    await _edit(cb, *await channel_picker_view(channels, user.channels_per_page, callback_data.pg))


PREVIEWABLE = {"photo", "video", "animation", "document", "audio"}


async def post_card(
    session: AsyncSession, user: User, post: Post, d: int, m: str, c: int
) -> tuple[str, InlineKeyboardMarkup, dict | None]:
    """The post's card: what it is, where and when it goes out, what to do with it; plus its first media to preview."""
    published = m == "p"
    zone = tz_of(user.tz)
    lines = [t("plan.post_title_published") if published else t("plan.post_title")]
    if post.is_ad:
        lines.append(t("cp.ad_booking") if ads.is_booking(post) else t("cp.ad_post"))
    lines.append("")
    first = post.parts[0]
    lines.append(f"{part_icon(first)} {html.escape(snippet(part_preview_text(first), 120)) or t('parts.no_text')}")
    if len(post.parts) > 1:
        lines.append(t("ed.part", n=1, total=len(post.parts)))
    lines.append("")
    start, end = day_bounds_utc(date.fromordinal(d), user.tz)
    pubs = await (pubs_repo.published_between if published else pubs_repo.pending_between)(
        session, user.id, start, end, channel_ids=[c] if c else None
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
    p = post.id
    if published:
        rows = [[btn(t("plan.edit"), Cp(a="edit", d=d, id=p, m=m, c=c))]]
    else:
        rows = [
            [btn(t("plan.edit"), Cp(a="edit", d=d, id=p, m=m, c=c)), btn(t("plan.move"), Cp(a="move", d=d, id=p, m=m, c=c))],
            [btn(t("plan.now"), Cp(a="now", d=d, id=p, m=m, c=c))],
            [btn(t("plan.drop"), Cp(a="drop", d=d, id=p, m=m, c=c))],
        ]
    rows.append([btn(t("btn.back"), Cp(a="day", d=d, m=m, c=c))])
    media = None
    if not first.poll and first.media and first.media[0].get("type") in PREVIEWABLE and first.media[0].get("file_id"):
        media = first.media[0]
    return "\n".join(lines), markup(rows), media


async def send_card(bot: Bot, chat_id: int, text: str, kb: InlineKeyboardMarkup, media: dict | None) -> None:
    """Sends the card with the post's first photo/video/… on top; falls back to text if Telegram refuses the file."""
    if media is not None:
        send = {
            "photo": bot.send_photo, "video": bot.send_video, "animation": bot.send_animation,
            "document": bot.send_document, "audio": bot.send_audio,
        }[media["type"]]
        try:
            await send(chat_id, media["file_id"], caption=text, reply_markup=kb)
            return
        except TelegramBadRequest:
            pass
    await bot.send_message(chat_id, text, reply_markup=kb, link_preview_options=NO_PREVIEW)


@router.callback_query(Cp.filter(F.a == "post"))
async def cp_post(cb: CallbackQuery, callback_data: Cp, bot: Bot, session: AsyncSession, user: User) -> None:
    post = await posts_repo.get_post(session, user.id, callback_data.id)
    if post is None or not post.parts:
        await cb.answer(t("err.post_not_found"), show_alert=True)
        return
    await cb.answer()
    text, kb, media = await post_card(session, user, post, callback_data.d, callback_data.m, callback_data.c)
    if media is None:
        await _edit(cb, text, kb)
        return
    if cb.message is not None:
        with suppress(TelegramBadRequest):
            await cb.message.delete()
    await send_card(bot, cb.from_user.id, text, kb, media)


async def open_from_link(message: Message, session: AsyncSession, user: User, arg: str) -> None:
    """/start cp_<post>_<tab>_<day>_<channel>: «Відкрити» links in plans sent before the list became a table."""
    try:
        _, post_id, mode, d, c = arg.split("_")
        post_id, d, c = int(post_id), int(d), int(c)
        date.fromordinal(d)
    except ValueError:
        post_id, mode, d, c = 0, "s", 0, 0
    post = await posts_repo.get_post(session, user.id, post_id) if post_id else None
    if post is None or not post.parts or mode not in ("s", "p"):
        await message.answer(t("err.post_not_found"))
        return
    with suppress(TelegramBadRequest):
        await message.delete()  # the /start line itself is just noise in the chat
    text, kb, media = await post_card(session, user, post, d, mode, c)
    await send_card(message.bot, message.chat.id, text, kb, media)


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
    report, _ = await publish_now(session, worker, post)
    await _edit(cb, report, markup([[btn(t("btn.back"), Cp(a="day", d=callback_data.d, c=callback_data.c))]]))


@router.callback_query(Cp.filter(F.a.in_({"drop", "dropok"})))
async def cp_drop(
    cb: CallbackQuery, callback_data: Cp, bot: Bot, session: AsyncSession, user: User, settings: Settings
) -> None:
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
    await _show_plan(cb, bot, *await plan_view(
        session, user, date.fromordinal(callback_data.d), channel_id=callback_data.c, multi=len(channels) > 1,
        settings=settings,
    ))


@router.callback_query(Cp.filter(F.a == "new"))
async def cp_new(
    cb: CallbackQuery, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher
) -> None:
    from flowpost.bot.handlers.create_post import start_post

    await cb.answer()
    if cb.message is not None:
        await start_post(cb.message, bot, session, state, user, publisher)
