"""«📣 Рекламний пост»: pick the channel, then send the ad — or book a slot for it and send it later."""
from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ad
from flowpost.bot.handlers.create_post import CONTENT, extract_content
from flowpost.bot.handlers.editor.view import NO_PREVIEW, open_editor, safe_delete
from flowpost.bot.keyboards.common import add_channel_inline_kb, btn, chunked, markup
from flowpost.bot.states import AdInput
from flowpost.db.models import Channel, Post, PostTarget, User
from flowpost.db.repo import channel_admins as channel_admins_repo
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.db.repo import publications as pubs_repo
from flowpost.i18n import t
from flowpost.services import ads
from flowpost.services.html_sanitize import snippet, visible_len
from flowpost.services.posts import (
    TEXT_LIMIT,
    channel_link_html,
    group_error,
    initial_options,
    options_of,
    part_preview_text,
    poll_from_message,
    post_is_empty,
)
from flowpost.services.publisher import Publisher
from flowpost.services.slots import WEEKDAYS, fmt_hm, tz_of

router = Router(name="ads")


async def _last_draft(session: AsyncSession, user: User) -> Post | None:
    """The latest ad left in the editor without being published, scheduled or cancelled."""
    ids = (await session.scalars(
        select(Post.id)
        .where(Post.owner_id == user.id, Post.is_ad.is_(True), Post.status == "draft")
        .order_by(Post.updated_at.desc())
        .limit(5)
    )).all()
    for post_id in ids:
        post = await posts_repo.get_post(session, user.id, post_id)
        if post is not None and post.targets and (not post_is_empty(post) or ads.is_booking(post)):
            return post
    return None


async def _start_view(session: AsyncSession, user: User) -> tuple[str, InlineKeyboardMarkup] | None:
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    if not channels:
        return None
    rows = chunked([btn(c.title, Ad(a="ch", c=c.id)) for c in channels], 2)
    draft = await _last_draft(session, user)
    if draft is not None:
        rows.append([btn(t("ad.restore"), Ad(a="draft", p=draft.id))])
    return t("ad.start"), markup(rows)


async def send_ad_start(message: Message, session: AsyncSession, state: FSMContext, user: User) -> None:
    await state.clear()
    view = await _start_view(session, user)
    if view is None:
        await message.answer(t("post.no_channels"), reply_markup=add_channel_inline_kb())
        return
    await message.answer(view[0], reply_markup=view[1], link_preview_options=NO_PREVIEW)


async def _swap(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    if cb.message is None:
        return
    try:
        await cb.message.edit_text(text, reply_markup=kb, link_preview_options=NO_PREVIEW)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await cb.message.answer(text, reply_markup=kb, link_preview_options=NO_PREVIEW)


async def _postable_channel(session: AsyncSession, user: User, channel_id: int) -> Channel | None:
    channel = await channels_repo.get_channel(session, user.id, channel_id)
    if channel is None:
        return None
    if channel.owner_id == user.id or await channel_admins_repo.has_permission(session, channel.id, user.id, "posts"):
        return channel
    return None


BOOKINGS_SHOWN = 10


async def _bookings(session: AsyncSession, user: User, channel: Channel) -> list[tuple[Post, object]]:
    """The channel's ads still to come: booked slots, confirmed or not, soonest first; those without a time last."""
    ids = (await session.scalars(
        select(Post.id)
        .join(PostTarget, PostTarget.post_id == Post.id)
        .where(PostTarget.channel_id == channel.id, Post.is_ad.is_(True), Post.status.in_(("draft", "scheduled")))
        .order_by(Post.created_at)
        .limit(50)
    )).all()
    found = []
    for post_id in ids:
        post = await posts_repo.get_post(session, user.id, post_id)
        if post is None or (post.status == "draft" and not ads.is_booking(post)):
            continue
        found.append((post, await pubs_repo.next_run(session, post.id)))
    found.sort(key=lambda item: (item[1] is None, item[1] or 0))
    return found[:BOOKINGS_SHOWN]


def _booking_label(user: User, post: Post, run_at) -> str:
    """«пт 9, 12:00 💰 НОРМ ЧИ…»: ⏳ while the booking waits for confirmation, 💰 once it's confirmed."""
    lang = user.lang if user.lang in WEEKDAYS else "uk"
    if run_at is None:
        when = t("ad.no_time")
    else:
        local = run_at.astimezone(tz_of(user.tz))
        when = f"{WEEKDAYS[lang][local.weekday()]} {local.day}, {fmt_hm(local)}"
    part = post.parts[0] if post.parts else None
    title = (snippet(part_preview_text(part), 40) if part is not None else "") or options_of(post)["ad_advertiser"] or ""
    return f"{when} {'⏳' if ads.is_booking(post) else '💰'} {title or t('parts.no_text')}"


async def channel_view(session: AsyncSession, user: User, channel: Channel) -> tuple[str, InlineKeyboardMarkup]:
    """«Рекламний пост у …»: send the ad, open one of the channel's bookings, or book a new slot."""
    bookings = await _bookings(session, user, channel)
    text = t("ad.channel", channel=channel_link_html(channel))
    if bookings:
        text += "\n\n" + t("ad.pick_booking")
    rows = [[btn(_booking_label(user, post, run_at), Ad(a="open", p=post.id))] for post, run_at in bookings]
    rows.append([btn(t("ad.new_booking"), Ad(a="book", c=channel.id))])
    rows.append([btn(t("ad.back"), Ad(a="start"))])
    return text, markup(rows)


@router.callback_query(Ad.filter(F.a == "start"))
async def ad_start(cb: CallbackQuery, session: AsyncSession, state: FSMContext, user: User) -> None:
    await cb.answer()
    await state.clear()
    view = await _start_view(session, user)
    if view is None:
        await _swap(cb, t("post.no_channels"), add_channel_inline_kb())
        return
    await _swap(cb, *view)


@router.callback_query(Ad.filter(F.a.in_({"ch", "book"})))
async def ad_channel(cb: CallbackQuery, callback_data: Ad, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel = await _postable_channel(session, user, callback_data.c)
    if channel is None:
        await cb.answer(t("err.post_not_found"), show_alert=True)
        return
    await cb.answer()
    booking = callback_data.a == "book"
    await state.set_state(AdInput.booking if booking else AdInput.content)
    await state.update_data(ad_channel=channel.id)
    if booking:
        text = t("ad.booking", channel=channel_link_html(channel))
        kb = markup([[btn(t("ad.back"), Ad(a="ch", c=channel.id))]])
    else:
        text, kb = await channel_view(session, user, channel)
    await _swap(cb, text, kb)


@router.callback_query(Ad.filter(F.a.in_({"draft", "open"})))
async def ad_draft(
    cb: CallbackQuery, callback_data: Ad, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post = await posts_repo.get_post(session, user.id, callback_data.p)
    allowed = ("draft",) if callback_data.a == "draft" else ("draft", "scheduled")
    if post is None or not post.is_ad or post.status not in allowed:
        await cb.answer(t("err.post_not_found"), show_alert=True)
        return
    await cb.answer()
    if cb.message:
        await safe_delete(bot, cb.message.chat.id, [cb.message.message_id])
    await open_editor(bot, cb.from_user.id, session, state, user, post, publisher)


@router.message(StateFilter(AdInput.content, AdInput.booking), CONTENT)
async def ad_content(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    state: FSMContext,
    user: User,
    publisher: Publisher,
    album: list[Message] | None = None,
) -> None:
    if message.text and message.text.startswith("/"):
        await message.answer(t("err.unknown_command"))
        return
    data = await state.get_data()
    channel = await _postable_channel(session, user, int(data.get("ad_channel") or 0))
    if channel is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    booking = await state.get_state() == AdInput.booking.state
    options = {**initial_options(channel, True), "ad_booking": booking}
    content: dict = {}
    if booking and not album and message.text and ads.looks_like_advertiser(message.text):
        options["ad_advertiser"] = message.text.strip()
    elif message.poll:
        content["poll"] = poll_from_message(message)
    else:
        text, media, source_signature = extract_content(album or [message])
        error = group_error(media)
        if error:
            await message.answer(t(error))
            return
        if visible_len(text) > TEXT_LIMIT:
            await message.answer(t("err.text_too_long", max=TEXT_LIMIT))
            return
        content = {"text": text, "media": media, "source_signature": source_signature}
    post = await posts_repo.create_post(session, channel.owner_id, [channel.id], is_ad=True, options=options, **content)
    note = t("ad.booked", name=html.escape(options["ad_advertiser"])) if options.get("ad_advertiser") else None
    await open_editor(bot, message.chat.id, session, state, user, post, publisher, note=note)


@router.message(StateFilter(AdInput.content, AdInput.booking))
async def ad_unsupported(message: Message) -> None:
    await message.answer(t("err.unsupported_content"))
