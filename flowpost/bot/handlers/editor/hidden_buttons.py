"""Editor → «Кнопки» → «Приховане продовження»: a button whose text pops up only for subscribers (or boosters).

Step by step: the button's name, the hidden text, then what outsiders see. With «AI-генератор» on, one request
makes one or several such buttons at once."""
from __future__ import annotations

import html
import secrets

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.ai import _quota_left
from flowpost.bot.handlers.editor.view import load_editor_post, post_from_callback, render_editor, show_panel
from flowpost.bot.keyboards.common import btn, markup
from flowpost.bot.middlewares.access import AccessMiddleware
from flowpost.bot.states import Editor
from flowpost.config import Settings
from flowpost.db.models import Channel, Post, User
from flowpost.db.repo import channels as channels_repo
from flowpost.i18n import t
from flowpost.services import analytics
from flowpost.services.ai import AIError, AIService
from flowpost.services.billing import limits
from flowpost.services.parsing import MAX_BUTTON_ROWS, MAX_BUTTON_TEXT
from flowpost.services.posts import BUTTON_STYLES, MAX_HIDDEN, bot_rows, giveaway_rows, plain_buttons
from flowpost.services.publisher import Publisher

router = Router(name="editor_hidden_buttons")

COLORS = ("none", *BUTTON_STYLES)


def color_kb(post_id: int, style: str | None, action: str, back: str):
    """The colour picker: each choice painted its own colour, `action` with v=<colour> picks one."""
    current = style or "none"

    def choice(c: str):
        return btn(("✅ " if c == current else "") + t(f"hc.color_{c}"), Ed(a=action, p=post_id, v=c), None if c == "none" else c)

    return markup([
        [choice("none"), choice("primary")],
        [choice("success"), choice("danger")],
        [btn(t("btn.back"), Ed(a=back, p=post_id))],
    ])


def _draft(data: dict) -> dict:
    return {"style": None, "ai": False, "audience": "subs", "step": 1, "name": "", "hidden": "", **(data.get("hc") or {})}


def _screen(post_id: int, d: dict) -> tuple[str, object]:
    p = post_id
    audience = t(f"hc.aud_{d['audience']}")
    if d["ai"]:
        text = t("hc.ai_title") + "\n\n" + t("hc.ai_help")
    else:
        text = t("hc.title") + "\n\n" + t("hc.intro")
        if d["step"] == 1:
            text += "\n\n" + t("hc.step1", who=t(f"hc.who_{d['audience']}"))
        elif d["step"] == 2:
            text += "\n\n" + t("hc.name_line", name=html.escape(d["name"])) + "\n\n" + t("hc.step2", max=MAX_HIDDEN)
        else:
            text += "\n\n" + t("hc.name_line", name=html.escape(d["name"])) + "\n\n" + t(f"hc.step3_{d['audience']}", max=MAX_HIDDEN)
    rows = [[
        btn(t("hc.color", color=t(f"hc.color_{d['style'] or 'none'}")), Ed(a="hc_color", p=p)),
        btn(("✅ " if d["ai"] else "⬜️ ") + t("hc.ai"), Ed(a="hc_ai", p=p)),
    ]]
    if d["ai"] or d["step"] > 1:
        rows.append([btn(t("hc.audience", who=audience), Ed(a="hc_aud", p=p))])
    if not d["ai"] and d["step"] == 3:
        rows.append([btn(t("hc.skip"), Ed(a="hc_skip", p=p))])
    rows.append([btn(t("hc.cancel"), Ed(a="btn", p=p))])
    return text, markup(rows)


async def _show(bot: Bot, chat_id: int, state: FSMContext, post_id: int, d: dict, *, resend: bool = False) -> None:
    await state.set_state(Editor.hidden_btn)
    await state.update_data(hc=d)
    text, kb = _screen(post_id, d)
    await show_panel(bot, chat_id, state, text, kb, resend=resend)


async def _add(session: AsyncSession, post: Post, idx: int, d: dict, made: list[dict]) -> bool:
    """Put the new buttons under the part, each in its own row; False when that's more rows than Telegram allows."""
    part = post.parts[idx]
    new = [[{
        "text": b["name"], "hid": secrets.token_hex(3), "hidden": b["hidden"], "locked": b.get("locked") or "",
        "audience": d["audience"], **({"style": d["style"]} if d["style"] else {}),
    }] for b in made]
    rows = plain_buttons(part.buttons) + bot_rows(part.buttons) + new
    if len(rows) > MAX_BUTTON_ROWS:
        return False
    part.buttons = rows + giveaway_rows(part.buttons)
    await session.flush()
    return True


@router.callback_query(Ed.filter(F.a == "btn_hidden"))
async def hc_start(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    await _show(bot, cb.from_user.id, state, post.id, _draft({}))


@router.callback_query(Ed.filter(F.a.in_({"hc_ai", "hc_aud", "hc_back"})))
async def hc_toggle(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    d = _draft(await state.get_data())
    if callback_data.a == "hc_ai":
        d["ai"] = not d["ai"]
    elif callback_data.a == "hc_aud":
        d["audience"] = "boost" if d["audience"] == "subs" else "subs"
    await _show(bot, cb.from_user.id, state, post.id, d)


@router.callback_query(Ed.filter(F.a == "hc_color"))
async def hc_color(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    d = _draft(await state.get_data())
    if callback_data.v in COLORS:  # picked: back to the step
        await cb.answer()
        d["style"] = None if callback_data.v == "none" else callback_data.v
        await _show(bot, cb.from_user.id, state, post.id, d)
        return
    await cb.answer()
    await show_panel(bot, cb.from_user.id, state, t("hc.color_title"), color_kb(post.id, d["style"], "hc_color", "hc_back"))


@router.callback_query(Ed.filter(F.a == "hc_skip"))
async def hc_skip(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    d = _draft(await state.get_data())
    if d["ai"] or d["step"] != 3:
        await cb.answer()
        return
    if not await _add(session, post, idx, d, [{"name": d["name"], "hidden": d["hidden"]}]):
        await cb.answer(t("err.buttons_rows", max=MAX_BUTTON_ROWS), show_alert=True)
        return
    await cb.answer()
    await state.update_data(hc=None)
    await render_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=t("hc.saved"))


@router.message(Editor.hidden_btn, F.text)
async def hc_input(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher,
    ai: AIService, settings: Settings,
) -> None:
    post, idx = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    d = _draft(await state.get_data())
    text = (message.text or "").strip()
    if d["ai"]:
        await _generate(message, bot, session, state, user, ai, settings, post, idx, d, text)
        return
    if d["step"] == 1:
        if not text or len(text) > MAX_BUTTON_TEXT:
            await message.answer(t("hc.bad_name", max=MAX_BUTTON_TEXT))
            return
        d.update(name=text, step=2)
    elif d["step"] == 2:
        if not text or len(text) > MAX_HIDDEN:
            await message.answer(t("hc.too_long", max=MAX_HIDDEN, n=len(text)))
            return
        d.update(hidden=text, step=3)
    else:
        if len(text) > MAX_HIDDEN:
            await message.answer(t("hc.too_long", max=MAX_HIDDEN, n=len(text)))
            return
        if not await _add(session, post, idx, d, [{"name": d["name"], "hidden": d["hidden"], "locked": text}]):
            await message.answer(t("err.buttons_rows", max=MAX_BUTTON_ROWS))
            return
        await state.update_data(hc=None)
        await render_editor(bot, message.chat.id, session, state, user, post, publisher, note=t("hc.saved"))
        return
    await _show(bot, message.chat.id, state, post.id, d, resend=True)


@router.message(Editor.hidden_btn)
async def hc_wrong(message: Message) -> None:
    await message.answer(t("err.expected_input"))


async def take_ai(
    bot: Bot, chat_id: int, session: AsyncSession, state: FSMContext, user: User,
    ai: AIService, settings: Settings, post: Post, back,
) -> Channel | None:
    """Charges one AI text to the post's channel and shows «working»; None (with the reason shown) when it can't.
    A failed request is refunded with `limits.add`."""
    channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
    primary = channels[0] if channels else None
    owner = user if post.owner_id == user.id else (await session.get(User, post.owner_id) or user)
    access = await AccessMiddleware._ai_access(session, settings, post, owner)
    if access is None:
        await show_panel(bot, chat_id, state, t("hc.ai_paid"), back, resend=True)
        return None
    if not ai.enabled:
        await show_panel(bot, chat_id, state, t("ai.disabled"), back, resend=True)
        return None
    if await _quota_left(session, user, settings, access) <= 0:
        await show_panel(bot, chat_id, state, t("ai.quota_over"), back, resend=True)
        return None
    if primary is None or not await limits.take(session, primary.id, "ai_text"):
        await show_panel(bot, chat_id, state, t("ai.quota_channel_over"), back, resend=True)
        return None
    await session.commit()  # the quota row stays locked no longer than the take
    await show_panel(bot, chat_id, state, t("ai.working"), None, resend=True)
    return primary


async def _generate(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    ai: AIService, settings: Settings, post: Post, idx: int, d: dict, request: str,
) -> None:
    chat_id = message.chat.id
    back = markup([[btn(t("btn.back"), Ed(a="hc_back", p=post.id))]])
    primary = await take_ai(bot, chat_id, session, state, user, ai, settings, post, back)
    if primary is None:
        return
    try:
        made = await ai.hidden_buttons(
            request, post=post.parts[idx].text_html, audience=d["audience"], max_name=MAX_BUTTON_TEXT,
            max_text=MAX_HIDDEN, style=primary.ai_style_prompt,
        )
    except AIError as e:
        await limits.add(session, primary.id, "ai_text", 1)
        await show_panel(bot, chat_id, state, t(e.key), back)
        return
    analytics.track(session, user.id, "ai_call", action="hidden_buttons")
    await state.update_data(hc_made=made, hc_request=request)
    lines = [t("hc.ai_result")]
    for b in made:
        lines += ["", f"🙈 <b>{html.escape(b['name'])}</b>", "🔓 " + html.escape(b["hidden"])]
        if b["locked"]:
            lines.append("🔒 " + html.escape(b["locked"]))
    kb = markup([
        [btn(t("hc.ai_apply"), Ed(a="hc_apply", p=post.id))],
        [btn(t("ai.again"), Ed(a="hc_again", p=post.id))],
        [btn(t("btn.back"), Ed(a="hc_back", p=post.id))],
    ])
    await show_panel(bot, chat_id, state, "\n".join(lines), kb)


@router.callback_query(Ed.filter(F.a == "hc_apply"))
async def hc_apply(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    data = await state.get_data()
    made = data.get("hc_made")
    if not made:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    if not await _add(session, post, idx, _draft(data), made):
        await cb.answer(t("err.buttons_rows", max=MAX_BUTTON_ROWS), show_alert=True)
        return
    await cb.answer()
    await state.update_data(hc=None, hc_made=None, hc_request=None)
    await render_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=t("hc.saved"))


@router.callback_query(Ed.filter(F.a == "hc_again"))
async def hc_again(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    ai: AIService, settings: Settings,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    data = await state.get_data()
    if not data.get("hc_request") or cb.message is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    await cb.answer()
    await _generate(cb.message, bot, session, state, user, ai, settings, post, idx, _draft(data), data["hc_request"])
