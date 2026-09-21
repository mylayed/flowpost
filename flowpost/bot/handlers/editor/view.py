"""Rendering of the post editor: preview messages + control panel."""
from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, LinkPreviewOptions
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.keyboards.editor import editor_kb
from flowpost.bot.states import Editor
from flowpost.db.models import Channel, Post, User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.db.repo import publications as pubs_repo
from flowpost.db.types import utcnow
from flowpost.i18n import set_locale, t
from flowpost.services.billing import entitlements
from flowpost.services.posts import options_of, part_is_empty, part_warnings
from flowpost.services.publisher import Publisher
from flowpost.services.slots import fmt_date, fmt_hm, tz_of

log = logging.getLogger(__name__)
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
_background: set[asyncio.Task] = set()  # strong references, so a running task isn't garbage-collected


async def safe_delete(bot: Bot, chat_id: int, ids: list[int | None]) -> None:
    ids = [i for i in ids if i]
    if not ids:
        return
    try:
        await bot.delete_messages(chat_id, ids)
    except TelegramAPIError:
        pass


def fmt_interval(minutes: int) -> str:
    if minutes % 1440 == 0:
        return t("fmt.days", n=minutes // 1440)
    if minutes % 60 == 0:
        return t("fmt.hours", n=minutes // 60)
    return t("fmt.minutes", n=minutes)


def is_published_mode(post: Post) -> bool:
    return post.status == "published"


async def load_editor_post(
    session: AsyncSession, user: User, state: FSMContext, post_id: int | None = None
) -> tuple[Post | None, int]:
    """Post currently open in the editor (or `post_id` from a callback) and the active part index."""
    data = await state.get_data()
    pid = post_id or data.get("post_id")
    if not pid:
        return None, 0
    post = await posts_repo.get_post(session, user.id, int(pid))
    if post is None:
        return None, 0
    part = int(data.get("part", 0)) if data.get("post_id") == post.id else 0
    part = max(0, min(part, len(post.parts) - 1))
    if data.get("post_id") != post.id or data.get("part") != part:
        await state.update_data(post_id=post.id, part=part)
    return post, part


async def post_from_callback(
    cb: CallbackQuery, session: AsyncSession, user: User, state: FSMContext, post_id: int
) -> tuple[Post | None, int]:
    post, part = await load_editor_post(session, user, state, post_id)
    if post is None:
        await cb.answer(t("err.post_not_found"), show_alert=True)
        return None, 0
    if cb.message is not None and (await state.get_data()).get("panel_id") != cb.message.message_id:
        await state.update_data(panel_id=cb.message.message_id)
    return post, part


def _summary(post: Post, opts: dict) -> list[str]:
    items = []
    if opts["signature"]:
        items.append(t("ed.sum_signature"))
    if opts["watermark"]:
        items.append(t("ed.sum_watermark"))
    if opts["ad_label"]:
        items.append(t("ed.sum_ad"))
    if opts["silent"]:
        items.append(t("ed.sum_silent"))
    if opts["protect"]:
        items.append(t("ed.sum_protect"))
    if not opts["link_preview"]:
        items.append(t("ed.sum_nopreview"))
    if opts["pin"]:
        items.append(t("ed.sum_pin_hours", hours=opts["pin_hours"]) if opts["pin_hours"] else t("ed.sum_pin"))
    if opts["auto_delete_hours"]:
        items.append(t("ed.sum_delete", hours=opts["auto_delete_hours"]))
    if opts["hidden_text"]:
        items.append(t("ed.sum_hidden"))
    if post.repeat and post.repeat.active:
        items.append(t("ed.sum_repeat", interval=fmt_interval(post.repeat.interval_minutes)))
    return items


async def panel_text(
    session: AsyncSession,
    user: User,
    post: Post,
    channels: list[Channel],
    part_idx: int,
    warnings: list[str],
    note: str | None,
) -> str:
    published = is_published_mode(post)
    if published:
        title = t("ed.title_published")
    elif post.is_ad:
        title = t("ed.title_ad")
    else:
        title = t("ed.title")
    lines = [title, t("ed.channels", names=", ".join(html.escape(c.title) for c in channels) or "—")]
    if len(post.parts) > 1:
        lines.append(t("ed.part", n=part_idx + 1, total=len(post.parts)))
    if not published:
        summary = _summary(post, options_of(post))
        if summary:
            lines.append("⚙️ " + " · ".join(summary))
        run_at = await pubs_repo.next_run(session, post.id)
        if run_at:
            local = run_at.astimezone(tz_of(user.tz))
            lines.append(t("ed.scheduled_at", date=fmt_date(local.date(), user.lang), time=fmt_hm(local)))
    lines.append("")
    part = post.parts[part_idx]
    if published:
        lines.append(t("ed.hint_published"))
    elif part.poll:
        lines.append(t("ed.hint_poll"))
    else:
        lines.append(t("ed.hint_empty") if part_is_empty(part) else t("ed.hint"))
    for key in warnings:
        lines.append("⚠️ " + t(key))
    if note:
        lines += ["", note]
    return "\n".join(lines)


async def show_panel(
    bot: Bot,
    chat_id: int,
    state: FSMContext,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    *,
    resend: bool = False,
) -> None:
    """Replace the editor panel content in place, or re-send it below the user's last message."""
    data = await state.get_data()
    panel_id = data.get("panel_id")
    if panel_id and resend:
        await safe_delete(bot, chat_id, [panel_id])
    elif panel_id:
        try:
            await bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=panel_id, reply_markup=reply_markup, link_preview_options=NO_PREVIEW
            )
            return
        except TelegramBadRequest as e:
            if "not modified" in str(e):
                return
    msg = await bot.send_message(chat_id, text, reply_markup=reply_markup, link_preview_options=NO_PREVIEW)
    await state.update_data(panel_id=msg.message_id)


async def render_editor(
    bot: Bot,
    chat_id: int,
    session: AsyncSession,
    state: FSMContext,
    user: User,
    post: Post,
    publisher: Publisher,
    *,
    note: str | None = None,
    preview: bool = True,
    defer_wm: bool = True,
) -> None:
    """The editor: the post's preview messages and the control panel under them. A video that needs a watermark
    takes a long time to render, so unless `defer_wm` is off (or the publisher can't finish it later) the preview
    shows the original at once and `_finish_wm_preview` swaps in the watermarked one when it's ready."""
    data = await state.get_data()
    part_idx = int(data.get("part", 0)) if data.get("post_id") == post.id else 0
    part_idx = max(0, min(part_idx, len(post.parts) - 1))
    await state.set_state(Editor.content)
    await state.update_data(post_id=post.id, part=part_idx)

    channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
    primary = channels[0] if channels else None
    warnings: list[str] = []
    published = is_published_mode(post)

    if not preview:
        text = await panel_text(session, user, post, channels, part_idx, warnings, note)
        await show_panel(bot, chat_id, state, text, editor_kb(post, part_idx, published=published))
        return

    await safe_delete(bot, chat_id, list(data.get("preview_ids") or []) + [data.get("panel_id")])
    preview_ids: list[int] = []
    part = post.parts[part_idx]
    deferred: list = []
    if not part_is_empty(part):
        try:
            result = await publisher.publish_post(
                post, primary, user.lang, chat_id=chat_id, preview=True, part_indexes=[part_idx], session=session,
                wm_allowed=await entitlements.extras_allowed(session, channels, utcnow()),
                defer_wm=deferred if defer_wm and publisher.sessionmaker is not None else None,
            )
            preview_ids = result.all_ids
            warnings += result.warnings
        except TelegramBadRequest as e:
            log.info("preview failed: %s", e)
            note = (note + "\n\n" if note else "") + t("warn.preview_failed", error=html.escape(e.message))
    warnings = part_warnings(
        part, options_of(post), primary, user.lang,
        is_last=part_idx == len(post.parts) - 1, premium_emoji=publisher.premium_emoji,
    ) + [w for w in warnings if w]
    if deferred:
        note = (note + "\n\n" if note else "") + t("ed.wm_rendering")
    text = await panel_text(session, user, post, channels, part_idx, list(dict.fromkeys(warnings)), note)
    panel = await bot.send_message(
        chat_id, text, reply_markup=editor_kb(post, part_idx, published=published), link_preview_options=NO_PREVIEW
    )
    await state.update_data(preview_ids=preview_ids, panel_id=panel.message_id)
    if deferred:
        task = asyncio.create_task(
            _finish_wm_preview(bot, chat_id, state, user.id, post.id, panel.message_id, publisher, deferred)
        )
        _background.add(task)
        task.add_done_callback(_background.discard)


async def _finish_wm_preview(
    bot: Bot, chat_id: int, state: FSMContext, user_id: int, post_id: int, panel_id: int,
    publisher: Publisher, deferred: list,
) -> None:
    """Render the deferred watermarks, then redraw the editor with them — unless the user has moved on from the
    editor screen they were shown, in which case the render is still kept and the next preview is quick."""
    try:
        await publisher.warm_watermarks(deferred)
        data = await state.get_data()
        if (
            data.get("post_id") != post_id or data.get("panel_id") != panel_id
            or await state.get_state() != Editor.content.state
        ):
            return
        async with publisher.sessionmaker() as session:  # type: ignore[misc]
            user = await session.get(User, user_id)
            post = await posts_repo.get_post(session, user_id, post_id)
            if user is None or post is None:
                return
            set_locale(user.lang)
            await render_editor(bot, chat_id, session, state, user, post, publisher, defer_wm=False)
            await session.commit()
    except Exception:  # noqa: BLE001 - nobody awaits this task
        log.exception("finishing the watermarked preview of post %s failed", post_id)


async def open_editor(
    bot: Bot,
    chat_id: int,
    session: AsyncSession,
    state: FSMContext,
    user: User,
    post: Post,
    publisher: Publisher,
    *,
    note: str | None = None,
) -> None:
    await state.set_state(Editor.content)
    await state.update_data(post_id=post.id, part=0, preview_ids=[], panel_id=None)
    await render_editor(bot, chat_id, session, state, user, post, publisher, note=note)


async def close_editor(bot: Bot, chat_id: int, state: FSMContext, *, delete_preview: bool = False) -> None:
    data = await state.get_data()
    ids: list[int | None] = [data.get("panel_id")]
    if delete_preview:
        ids += list(data.get("preview_ids") or [])
    await safe_delete(bot, chat_id, ids)
    await state.clear()
