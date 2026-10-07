"""Editor → «ШІ-асистент» → free tools: «Перевірити» before publishing and «Серія з довгого тексту».

Unlike the other AI actions these need no paid plan or AI-text quota: the owner and any channel admin with post
rights can use them, limited only by a daily per-user cap.
"""
from __future__ import annotations

import html
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.schedule import show_schedule
from flowpost.bot.handlers.editor.view import (
    is_published_mode,
    load_editor_post,
    post_from_callback,
    render_editor,
    show_panel,
)
from flowpost.bot.keyboards.common import btn, markup
from flowpost.bot.states import Editor
from flowpost.config import Settings
from flowpost.db.models import Post, User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services import analytics
from flowpost.services.ai import AIError, AIService
from flowpost.services.article import ArticleError, fetch_text
from flowpost.services.html_sanitize import snippet, visible_len
from flowpost.services.parsing import normalize_url
from flowpost.services.posts import CAPTION_LIMIT, TEXT_LIMIT, render_signature
from flowpost.services.publisher import Publisher

router = Router(name="editor_ai_tools")
MIN_SERIES_SOURCE = 500  # visible characters; anything shorter reads fine as one post
PANEL_LIMIT = 3900
CHECK_ICONS = {"error": "📝", "surzhyk": "🗣", "fact": "⚠️"}


async def free_left(session: AsyncSession, user: User, settings: Settings) -> int:
    used = await analytics.count_since(session, user.id, "ai_free", utcnow() - timedelta(days=1))
    return settings.ai_free_daily_limit - used


async def _primary(session: AsyncSession, user: User, post: Post):
    channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
    return channels[0] if channels else None


async def _can_run(bot: Bot, chat_id: int, session: AsyncSession, state: FSMContext, user: User, ai: AIService,
                   settings: Settings, back, *, resend: bool) -> bool:
    if not ai.enabled:
        await show_panel(bot, chat_id, state, t("ai.disabled"), back, resend=resend)
        return False
    if await free_left(session, user, settings) <= 0:
        await show_panel(bot, chat_id, state, t("ai.free_quota_over"), back, resend=resend)
        return False
    return True


async def _show(bot: Bot, chat_id: int, state: FSMContext, text: str, kb) -> None:
    try:
        await show_panel(bot, chat_id, state, text, kb)
    except TelegramBadRequest:
        await show_panel(bot, chat_id, state, html.escape(text), kb)


# ---- «Перевірити» ----------------------------------------------------------------------------------------------


def check_report(report: dict, length: int, limit: int) -> str:
    lines = [t("check.title"), ""]
    issues = report["issues"]
    if not issues:
        lines.append(t("check.clean"))
    for kind in CHECK_ICONS:
        found = [i for i in issues if i["kind"] == kind]
        if not found:
            continue
        lines += ["", f"{CHECK_ICONS[kind]} <b>{t('check.kind_' + kind)}</b>"]
        lines += [f"• «{html.escape(i['quote'])}» — {html.escape(i['note'])}" for i in found]
    lines.append("")
    if length > limit:
        lines.append(t("check.over_limit", n=length, limit=limit))
    elif report["too_long"]:
        lines.append(t("check.too_long", n=length) + (f" {html.escape(report['length_note'])}" if report["length_note"] else ""))
    else:
        lines.append(t("check.length_ok", n=length))
    if report["has_cta"]:
        lines.append(t("check.cta_ok"))
    else:
        lines.append(t("check.cta_missing") + (f" {html.escape(report['cta_note'])}" if report["cta_note"] else ""))
    text = "\n".join(lines)
    return text if len(text) <= PANEL_LIMIT else text[:PANEL_LIMIT].rsplit("\n", 1)[0] + "\n…"


async def run_check(
    bot: Bot, chat_id: int, session: AsyncSession, state: FSMContext, user: User, ai: AIService, settings: Settings,
    post: Post, idx: int,
) -> None:
    back = markup([[btn(t("btn.back"), Ed(a="ai", p=post.id))]])
    if not await _can_run(bot, chat_id, session, state, user, ai, settings, back, resend=False):
        return
    part = post.parts[idx]
    primary = await _primary(session, user, post)
    limit = CAPTION_LIMIT if part.media else TEXT_LIMIT
    if primary is not None and (post.options or {}).get("signature", True):
        limit -= visible_len(render_signature(primary, (post.options or {}).get("signature_tpl") or 0)) + 2
    await show_panel(bot, chat_id, state, t("check.working"), None)
    try:
        report = await ai.check_post(part.text_html, lang=user.lang, style=primary.ai_style_prompt if primary else None)
    except AIError as e:
        await show_panel(bot, chat_id, state, t(e.key), back)
        return
    analytics.track(session, user.id, "ai_free", action="check")
    fixable = any(i["kind"] in ("error", "surzhyk") for i in report["issues"])
    corrected = report["corrected"] if fixable and report["corrected"] != part.text_html.strip() else None
    await state.update_data(check_fix=corrected, check_part=idx)
    rows = []
    if corrected:
        rows.append([btn(t("check.apply_fix"), Ed(a="chk_fix", p=post.id))])
    rows += [[btn(t("check.again"), Ed(a="chk", p=post.id))], [btn(t("btn.back"), Ed(a="home", p=post.id))]]
    await _show(bot, chat_id, state, check_report(report, visible_len(part.text_html), limit), markup(rows))


@router.callback_query(Ed.filter(F.a == "chk"))
async def ed_check(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    ai: AIService, settings: Settings,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    if not post.parts[idx].text_html.strip():
        await cb.answer(t("ai.need_text"), show_alert=True)
        return
    await cb.answer()
    await state.set_state(Editor.content)
    await run_check(bot, cb.from_user.id, session, state, user, ai, settings, post, idx)


@router.callback_query(Ed.filter(F.a == "chk_fix"))
async def ed_check_fix(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    data = await state.get_data()
    fixed, idx = data.get("check_fix"), data.get("check_part")
    if not fixed or idx is None or not 0 <= idx < len(post.parts):
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    await cb.answer(t("check.fixed"))
    post.parts[idx].text_html = fixed
    await state.update_data(check_fix=None, part=idx)
    await session.flush()
    await render_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=t("check.fixed"))


# ---- «Серія з довгого тексту» ----------------------------------------------------------------------------------


def apply_series(post: Post, texts: list[str]) -> None:
    """The series texts become the post's messages in order; media already in a message stays with it, and
    leftover messages keep only their media (empty ones are removed)."""
    for i, text in enumerate(texts):
        part = post.parts[i] if i < len(post.parts) else posts_repo.add_part(post)
        part.text_html = text
    for part in list(post.parts[len(texts):]):
        if part.media:
            part.text_html = ""
        else:
            post.parts.remove(part)
    for i, part in enumerate(post.parts):
        part.position = i


async def run_series(
    bot: Bot, chat_id: int, session: AsyncSession, state: FSMContext, user: User, ai: AIService, settings: Settings,
    post: Post, source: str, *, resend: bool = False,
) -> None:
    await state.set_state(Editor.content)
    back = markup([[btn(t("btn.back"), Ed(a="sr", p=post.id))]])
    if not await _can_run(bot, chat_id, session, state, user, ai, settings, back, resend=resend):
        return
    url = normalize_url(source) if len(source.split()) == 1 else None
    if url and url.startswith("http"):
        await show_panel(bot, chat_id, state, t("series.fetching"), None, resend=resend)
        resend = False
        try:
            source = await fetch_text(url)
        except ArticleError as e:
            await show_panel(bot, chat_id, state, t(e.key), back)
            return
    elif visible_len(source) < MIN_SERIES_SOURCE:
        await show_panel(bot, chat_id, state, t("series.too_short", n=MIN_SERIES_SOURCE), back, resend=resend)
        return
    primary = await _primary(session, user, post)
    limit = TEXT_LIMIT
    if primary is not None and (post.options or {}).get("signature", True):
        limit -= visible_len(render_signature(primary, (post.options or {}).get("signature_tpl") or 0)) + 2
    await show_panel(bot, chat_id, state, t("series.working"), None, resend=resend)
    try:
        texts = await ai.split_series(
            source, lang=user.lang, limit=min(3500, limit), style=primary.ai_style_prompt if primary else None,
        )
    except AIError as e:
        await show_panel(bot, chat_id, state, t(e.key), back)
        return
    analytics.track(session, user.id, "ai_free", action="series")
    await state.update_data(series=texts, series_src=source)
    per = max(120, (PANEL_LIMIT - 400) // len(texts))
    lines = [t("series.result", n=len(texts)), ""]
    for i, text in enumerate(texts, 1):
        lines += [f"<b>{i}.</b> {html.escape(snippet(text, per))}", ""]
    lines.append(t("series.result_help"))
    kb = markup([
        [btn(t("series.apply_schedule"), Ed(a="sr_ok", p=post.id, v="sch"))],
        [btn(t("series.apply"), Ed(a="sr_ok", p=post.id))],
        [btn(t("ai.again"), Ed(a="sr_again", p=post.id))],
        [btn(t("btn.back"), Ed(a="ai", p=post.id))],
    ])
    await _show(bot, chat_id, state, "\n".join(lines), kb)


@router.callback_query(Ed.filter(F.a == "sr"))
async def ed_series(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    if is_published_mode(post):
        await cb.answer(t("series.published"), show_alert=True)
        return
    if any(part.poll for part in post.parts):
        await cb.answer(t("series.has_poll"), show_alert=True)
        return
    await cb.answer()
    await state.set_state(Editor.ai_series)
    rows = []
    if visible_len(post.parts[idx].text_html) >= MIN_SERIES_SOURCE:
        rows.append([btn(t("series.use_current"), Ed(a="sr_cur", p=post.id))])
    rows.append([btn(t("btn.back"), Ed(a="ai", p=post.id))])
    await show_panel(bot, cb.from_user.id, state, t("series.prompt"), markup(rows))


@router.callback_query(Ed.filter(F.a.in_({"sr_cur", "sr_again"})))
async def ed_series_run(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    ai: AIService, settings: Settings,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    source = post.parts[idx].text_html if callback_data.a == "sr_cur" else (await state.get_data()).get("series_src")
    if not source:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    await cb.answer()
    await run_series(bot, cb.from_user.id, session, state, user, ai, settings, post, source)


@router.message(Editor.ai_series, F.text)
async def in_series_source(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    ai: AIService, settings: Settings,
) -> None:
    post, _ = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    await run_series(bot, message.chat.id, session, state, user, ai, settings, post, message.html_text, resend=True)


@router.message(Editor.ai_series)
async def in_series_wrong(message: Message) -> None:
    await message.answer(t("series.prompt"))


@router.callback_query(Ed.filter(F.a == "sr_ok"))
async def ed_series_apply(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    texts = (await state.get_data()).get("series")
    if not texts or is_published_mode(post) or any(part.poll for part in post.parts):
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    await cb.answer(t("series.applied", n=len(texts)))
    apply_series(post, texts)
    await state.update_data(series=None, series_src=None, part=0)
    await session.flush()
    await render_editor(bot, cb.from_user.id, session, state, user, post, publisher,
                        note=t("series.applied", n=len(texts)))
    if callback_data.v == "sch":
        await show_schedule(bot, cb.from_user.id, session, state, user, post)
