"""Editor → «ШІ-асистент»."""
from __future__ import annotations

import html
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Cs, Ed
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
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services import analytics
from flowpost.services.ai import AIError, AIService
from flowpost.services.billing.subscriptions import Access, get_access
from flowpost.services.html_sanitize import visible_len
from flowpost.services.posts import CAPTION_LIMIT, TEXT_LIMIT, render_signature
from flowpost.services.publisher import Publisher

router = Router(name="editor_ai")
MAX_IMAGE = 5 * 1024 * 1024


def ai_menu(post: Post, primary_channel_id: int | None, enabled: bool, left: int | None) -> tuple[str, object]:
    p = post.id
    lines = [t("ai.title"), ""]
    lines.append(t("ai.help") if enabled else t("ai.disabled"))
    if left is not None:
        lines.append(t("ai.quota", left=max(0, left)))
    rows = [
        [btn(t("ai.format"), Ed(a="ai_run", p=p, v="format"))],
        [btn(t("ai.shorten"), Ed(a="ai_run", p=p, v="shorten")), btn(t("ai.fix"), Ed(a="ai_run", p=p, v="fix"))],
        [btn(t("ai.emoji"), Ed(a="ai_run", p=p, v="emoji")), btn(t("ai.custom"), Ed(a="ai_custom", p=p))],
        [btn(t("ai.screenshot"), Ed(a="ai_shot", p=p))],
    ]
    if primary_channel_id and not is_published_mode(post):
        rows.append([btn(t("ai.style"), Cs(a="ai_style", c=primary_channel_id, p=p))])
    rows.append([btn(t("btn.back"), Ed(a="home", p=p))])
    return "\n".join(lines), markup(rows)


async def _quota_left(session: AsyncSession, user: User, settings: Settings, access: Access | None) -> int:
    limit = settings.ai_daily_limit_paid if access and access.kind == "paid" else settings.ai_daily_limit_trial
    used = await analytics.count_since(session, user.id, "ai_call", utcnow() - timedelta(days=1))
    return limit - used


@router.callback_query(Ed.filter(F.a == "ai"))
async def ed_ai_menu(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    ai: AIService, settings: Settings,
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    await state.set_state(Editor.content)
    channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
    left =await _quota_left(session, user, settings, await get_access(session, user)) if ai.enabled else None
    text, kb = ai_menu(post, channels[0].id if channels else None, ai.enabled, left)
    await show_panel(bot, cb.from_user.id, state, text, kb)


async def run_ai(
    bot: Bot,
    chat_id: int,
    session: AsyncSession,
    state: FSMContext,
    user: User,
    ai: AIService,
    settings: Settings,
    access: Access | None,
    post: Post,
    idx: int,
    action: str,
    *,
    instruction: str | None = None,
    image_file_id: str | None = None,
    resend: bool = False,
) -> None:
    await state.set_state(Editor.content)
    back = markup([[btn(t("btn.back"), Ed(a="ai", p=post.id))]])
    if not ai.enabled:
        await show_panel(bot, chat_id, state, t("ai.disabled"), back, resend=resend)
        return
    if await _quota_left(session, user, settings, access) <= 0:
        await show_panel(bot, chat_id, state, t("ai.quota_over"), back, resend=resend)
        return
    part = post.parts[idx]
    channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
    primary = channels[0] if channels else None
    limit = CAPTION_LIMIT if part.media else TEXT_LIMIT
    if primary is not None and (post.options or {}).get("signature", True):
        limit -= visible_len(render_signature(primary)) + 2
    image = None
    if image_file_id:
        buf = await bot.download(image_file_id)
        image = (buf.getvalue(), "image/jpeg")

    await show_panel(bot, chat_id, state, t("ai.working"), None, resend=resend)
    try:
        result = await ai.generate(
            action,
            text=part.text_html,
            lang=user.lang,
            limit=max(200, limit),
            style=primary.ai_style_prompt if primary else None,
            instruction=instruction,
            image=image,
        )
    except AIError as e:
        await show_panel(bot, chat_id, state, t(e.key), back)
        return
    analytics.track(session, user.id, "ai_call", action=action)
    await state.update_data(ai_result=result, ai_action=action, ai_instruction=instruction, ai_image=image_file_id)
    kb = markup([
        [btn(t("ai.apply"), Ed(a="ai_apply", p=post.id))],
        [btn(t("ai.again"), Ed(a="ai_again", p=post.id))],
        [btn(t("btn.back"), Ed(a="ai", p=post.id))],
    ])
    shown = result if len(result) < 3800 else result[:3800] + "…"
    try:
        await show_panel(bot, chat_id, state, t("ai.result_title") + "\n\n" + shown, kb)
    except TelegramBadRequest:
        await show_panel(bot, chat_id, state, t("ai.result_title") + "\n\n" + html.escape(shown), kb)


@router.callback_query(Ed.filter(F.a == "ai_run"), flags={"paid": True})
async def ed_ai_run(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    ai: AIService, settings: Settings, access: Access,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    if not post.parts[idx].text_html.strip():
        await cb.answer(t("ai.need_text"), show_alert=True)
        return
    await cb.answer()
    await run_ai(bot, cb.from_user.id, session, state, user, ai, settings, access, post, idx, callback_data.v)


@router.callback_query(Ed.filter(F.a == "ai_again"), flags={"paid": True})
async def ed_ai_again(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    ai: AIService, settings: Settings, access: Access,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    data = await state.get_data()
    action = data.get("ai_action")
    if not action:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    await cb.answer()
    await run_ai(
        bot, cb.from_user.id, session, state, user, ai, settings, access, post, idx, action,
        instruction=data.get("ai_instruction"), image_file_id=data.get("ai_image"),
    )


@router.callback_query(Ed.filter(F.a == "ai_apply"))
async def ed_ai_apply(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    _missing = object()
    result = (await state.get_data()).get("ai_result", _missing)
    if result is _missing or result is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    await cb.answer(t("ai.applied"))
    post.parts[idx].text_html = result
    await state.update_data(ai_result=None)
    await session.flush()
    await render_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=t("ai.applied"))


@router.callback_query(Ed.filter(F.a.in_({"ai_custom", "ai_shot"})))
async def ed_ai_ask(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    custom = callback_data.a == "ai_custom"
    await state.set_state(Editor.ai_custom if custom else Editor.ai_image)
    back = markup([[btn(t("btn.back"), Ed(a="ai", p=post.id))]])
    await show_panel(bot, cb.from_user.id, state, t("ai.custom_prompt") if custom else t("ai.screenshot_prompt"), back)


@router.message(Editor.ai_custom, F.text, flags={"paid": True})
async def in_ai_custom(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    ai: AIService, settings: Settings, access: Access,
) -> None:
    post, idx = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    await run_ai(
        bot, message.chat.id, session, state, user, ai, settings, access, post, idx, "custom",
        instruction=(message.text or "")[:1500], resend=True,
    )


@router.message(Editor.ai_image, F.photo | F.document, flags={"paid": True})
async def in_ai_image(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    ai: AIService, settings: Settings, access: Access,
) -> None:
    post, idx = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    if message.document:
        if not (message.document.mime_type or "") in ("image/jpeg", "image/png", "image/webp"):
            await message.answer(t("ai.screenshot_prompt"))
            return
        if (message.document.file_size or 0) > MAX_IMAGE:
            await message.answer(t("ai.image_too_big"))
            return
        file_id = message.document.file_id
    else:
        file_id = message.photo[-1].file_id
    await run_ai(
        bot, message.chat.id, session, state, user, ai, settings, access, post, idx, "screenshot",
        image_file_id=file_id, resend=True,
    )


@router.message(Editor.ai_custom)
@router.message(Editor.ai_image)
async def in_ai_wrong(message: Message) -> None:
    await message.answer(t("err.expected_input"))
