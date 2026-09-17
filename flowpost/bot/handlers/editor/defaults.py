"""The «Готово» screen shown after a post is scheduled, and the per-channel defaults it can save.

«Зберегти форматування та налаштування» copies the post's settings (signature, watermark, silent,
link preview, pinning, auto-delete, comments) and its buttons onto every channel the post goes to,
so the next post created there starts with the same setup.
"""
from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.view import NO_PREVIEW, post_from_callback
from flowpost.bot.keyboards.common import btn, markup
from flowpost.db.models import Post, User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import publications as pubs_repo
from flowpost.i18n import t
from flowpost.services.html_sanitize import snippet
from flowpost.services.delivery import publication_message_ids
from flowpost.services.posts import (
    channel_link,
    channel_link_html,
    message_link,
    options_of,
    part_preview_text,
    post_defaults,
)
from flowpost.services.slots import fmt_when_full, tz_of

router = Router(name="editor_defaults")


def post_title(post: Post) -> str:
    """The post's first line, short enough to sit inside «…» in a one-line confirmation."""
    part = post.parts[0] if post.parts else None
    text = snippet(part_preview_text(part), 48) if part is not None else ""
    return html.escape(text) or t("parts.no_text")


def saved_items(post: Post) -> list[str]:
    """Human-readable list of what «Зберегти за замовчуванням» will carry over."""
    opts = options_of(post)
    items = [t("ed.sum_signature") if opts["signature"] else t("ed.def_no_signature")]
    if opts["watermark"]:
        items.append(t("ed.sum_watermark"))
    if opts["silent"]:
        items.append(t("ed.sum_silent"))
    if opts["protect"]:
        items.append(t("ed.sum_protect"))
    if not opts["link_preview"]:
        items.append(t("ed.sum_nopreview"))
    if not opts["comments"]:
        items.append(t("ed.def_no_comments"))
    if opts["pin"]:
        items.append(t("ed.sum_pin_hours", hours=opts["pin_hours"]) if opts["pin_hours"] else t("ed.sum_pin"))
    if opts["auto_delete_hours"]:
        items.append(t("ed.sum_delete", hours=opts["auto_delete_hours"]))
    buttons = post.parts[0].buttons if post.parts else []
    if buttons:
        items.append(t("ed.def_buttons", n=sum(len(row) for row in buttons)))
    return items


async def _published_channels_line(session: AsyncSession, user: User, post: Post) -> str:
    """Channel names linking straight to the message this post became in each of them."""
    channels = {c.id: c for c in await channels_repo.get_by_ids(session, user.id, post.channel_ids)}
    links = []
    for pub in await pubs_repo.published_for_post(session, post.id):
        channel = channels.get(pub.channel_id)
        if channel is None:
            continue
        ids = publication_message_ids(pub)
        link = message_link(channel, ids[0]) if ids else channel_link(channel)
        links.append(f'<a href="{link}">{html.escape(channel.title or "")}</a>')
    return ", ".join(links) or ", ".join(channel_link_html(c) for c in channels.values())


async def done_screen(
    session: AsyncSession, user: User, post: Post, *, note: str | None = None, with_button: bool = True
) -> tuple[str, InlineKeyboardMarkup | None]:
    """«Готово ✈️ Пост «…» заплановано на …» (or «опубліковано в …») plus the «save as default» offer."""
    if post.status == "published":
        text = t("pub.done", title=post_title(post),
                 channels=await _published_channels_line(session, user, post) or "—")
    else:
        run_at = await pubs_repo.next_run(session, post.id)
        channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
        channels_line = ", ".join(channel_link_html(c) for c in channels) or "—"
        if run_at is None:
            text = t("sch.done_no_time", title=post_title(post), channels=channels_line)
        else:
            local = run_at.astimezone(tz_of(user.tz))
            text = t(
                "sch.done", title=post_title(post),
                when=fmt_when_full(local.date(), local.time(), user.lang), channels=channels_line,
            )
    if note:
        text += "\n\n" + note
    kb = markup([[btn(t("ed.def_btn"), Ed(a="defs", p=post.id))]]) if with_button else None
    return text, kb


async def _swap(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None) -> None:
    """Replace the message the button sits on; the editor panel state is already cleared by then."""
    if cb.message is None:
        return
    try:
        await cb.message.edit_text(text, reply_markup=kb, link_preview_options=NO_PREVIEW)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await cb.message.answer(text, reply_markup=kb, link_preview_options=NO_PREVIEW)


@router.callback_query(Ed.filter(F.a == "defs"))
async def ed_defaults_ask(
    cb: CallbackQuery, callback_data: Ed, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    items = saved_items(post)
    text = "\n\n".join([
        t("ed.def_title"),
        t("ed.def_confirm"),
        t("ed.def_saving", items=" · ".join(items)),
        f"<blockquote expandable>{t('ed.def_help_title')}\n{t('ed.def_help')}</blockquote>",
    ])
    kb = markup([
        [btn(t("ed.def_save"), Ed(a="defsok", p=post.id), style="primary")],
        [btn(t("ed.def_back"), Ed(a="defsx", p=post.id))],
    ])
    await _swap(cb, text, kb)


@router.callback_query(Ed.filter(F.a == "defsx"))
async def ed_defaults_back(
    cb: CallbackQuery, callback_data: Ed, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    text, kb = await done_screen(session, user, post)
    await _swap(cb, text, kb)


@router.callback_query(Ed.filter(F.a == "defsok"))
async def ed_defaults_save(
    cb: CallbackQuery, callback_data: Ed, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
    if not channels:
        await cb.answer(t("post.no_channels"), show_alert=True)
        return
    defaults = post_defaults(post)
    for channel in channels:
        channel.post_defaults = defaults
    await session.flush()
    await cb.answer(t("ed.def_saved_short"))
    names = ", ".join(html.escape(c.title) for c in channels)
    text, kb = await done_screen(
        session, user, post, note=t("ed.def_saved", channels=names), with_button=False
    )
    await _swap(cb, text, kb)

