"""Editor → «Кнопки» → «Вікторина»: answer buttons under the post. A tap shows that answer's comment (right or
wrong) and how many people answered the same; only subscribers (or boosters) may answer, and only once.

Each answer goes step by step: its text on the button, the comment, then what outsiders see. After an answer is
added the preview shows it at once and the next text sent starts the next answer, until «Завершити опитування».
With «AI-генератор» on, one request makes the whole quiz."""
from __future__ import annotations

import html
import secrets

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.hidden_buttons import COLORS, color_kb, take_ai
from flowpost.bot.handlers.editor.view import load_editor_post, post_from_callback, render_editor, show_panel
from flowpost.bot.keyboards.common import btn, markup
from flowpost.bot.states import Editor
from flowpost.config import Settings
from flowpost.db.models import Post, User
from flowpost.i18n import t
from flowpost.services import analytics
from flowpost.services.ai import AIError, AIService
from flowpost.services.billing import limits
from flowpost.services.parsing import MAX_BUTTON_ROWS, MAX_BUTTON_TEXT, MAX_BUTTONS_PER_ROW
from flowpost.services.posts import MAX_HIDDEN, bot_rows, giveaway_rows, plain_buttons, quiz_locked_text
from flowpost.services.publisher import Publisher

router = Router(name="editor_quiz")

MAX_COMMENT = 150  # the pop-up holds 200 characters, and the answer statistics go under the comment


def _draft(data: dict) -> dict:
    return {
        "quiz": "", "style": None, "ai": False, "audience": "subs", "step": 1, "text": "", "comment": "",
        "locked": "", "newrow": True, "n": 0, **(data.get("qz") or {}),
    }


def _screen(post_id: int, d: dict) -> tuple[str, object]:
    p = post_id
    color = btn(t("hc.color", color=t(f"hc.color_{d['style'] or 'none'}")), Ed(a="qz_color", p=p))
    audience = btn(t("hc.audience", who=t(f"hc.aud_{d['audience']}")), Ed(a="qz_aud", p=p))
    if d["step"] == 2:
        return t("qz.step2", max=MAX_HIDDEN), markup([[audience], [btn(t("btn.back"), Ed(a="qz_prev", p=p))]])
    if d["step"] == 3:
        current = html.escape(quiz_locked_text({"locked": d["locked"], "audience": d["audience"]}))
        return t(f"qz.step3_{d['audience']}", current=current), markup([
            [btn(t("btn.back"), Ed(a="qz_prev", p=p)), btn(t("qz.continue"), Ed(a="qz_next", p=p))],
        ])
    if d["n"]:  # an answer was just added: the next text starts another one
        place = t("qz.place_new") if d["newrow"] else t("qz.place_same")
        return t("qz.added", n=d["n"]), markup([
            [color],
            [btn(t("qz.place", place=place), Ed(a="qz_row", p=p))],
            [btn(t("qz.done"), Ed(a="qz_done", p=p))],
        ])
    if d["ai"]:
        return t("qz.ai_title") + "\n\n" + t("qz.ai_help"), markup([
            [color, btn("✅ " + t("hc.ai"), Ed(a="qz_ai", p=p))],
            [audience],
            [btn(t("hc.cancel"), Ed(a="btn", p=p))],
        ])
    return t("qz.title") + "\n\n" + t("qz.intro") + "\n\n" + t("qz.step1"), markup([
        [color, btn("⬜️ " + t("hc.ai"), Ed(a="qz_ai", p=p))],
        [btn(t("hc.cancel"), Ed(a="btn", p=p))],
    ])


async def _show(bot: Bot, chat_id: int, state: FSMContext, post_id: int, d: dict, *, resend: bool = False) -> None:
    await state.set_state(Editor.quiz)
    await state.update_data(qz=d)
    text, kb = _screen(post_id, d)
    await show_panel(bot, chat_id, state, text, kb, resend=resend)


def _answer(d: dict, text: str, comment: str) -> dict:
    return {
        "text": text, "hid": secrets.token_hex(3), "quiz": d["quiz"], "comment": comment, "locked": d["locked"],
        "audience": d["audience"], **({"style": d["style"]} if d["style"] else {}),
    }


async def _add(session: AsyncSession, post: Post, idx: int, d: dict, answers: list[dict], *, same_row: bool) -> bool:
    """Put answers under the part — the first one next to the quiz's last answer when `same_row` and there's room,
    the rest in rows of their own; False when that's more rows than Telegram allows."""
    part = post.parts[idx]
    rows = [list(r) for r in bot_rows(part.buttons)]
    for i, answer in enumerate(answers):
        last = rows[-1] if rows else []
        if i == 0 and same_row and last and last[-1].get("quiz") == d["quiz"] and len(last) < MAX_BUTTONS_PER_ROW:
            last.append(answer)
        else:
            rows.append([answer])
    rows = plain_buttons(part.buttons) + rows
    if len(rows) > MAX_BUTTON_ROWS:
        return False
    part.buttons = rows + giveaway_rows(part.buttons)
    await session.flush()
    return True


@router.callback_query(Ed.filter(F.a == "btn_quiz"))
async def qz_start(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    await _show(bot, cb.from_user.id, state, post.id, _draft({"qz": {"quiz": secrets.token_hex(3)}}))


@router.callback_query(Ed.filter(F.a.in_({"qz_ai", "qz_aud", "qz_row", "qz_prev", "qz_back"})))
async def qz_toggle(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    d = _draft(await state.get_data())
    if callback_data.a == "qz_ai":
        d["ai"] = not d["ai"]
    elif callback_data.a == "qz_aud":
        d["audience"] = "boost" if d["audience"] == "subs" else "subs"
    elif callback_data.a == "qz_row":
        d["newrow"] = not d["newrow"]
    elif callback_data.a == "qz_prev":
        d["step"] = max(1, d["step"] - 1)
    await _show(bot, cb.from_user.id, state, post.id, d)


@router.callback_query(Ed.filter(F.a == "qz_color"))
async def qz_color(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    d = _draft(await state.get_data())
    if callback_data.v in COLORS:  # picked: back to the step
        d["style"] = None if callback_data.v == "none" else callback_data.v
        await _show(bot, cb.from_user.id, state, post.id, d)
        return
    await show_panel(bot, cb.from_user.id, state, t("hc.color_title"), color_kb(post.id, d["style"], "qz_color", "qz_back"))


async def _save(
    bot: Bot, chat_id: int, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher,
    post: Post, idx: int, d: dict,
) -> str | None:
    """Adds the drafted answer and shows it in the preview; the error text when it doesn't fit."""
    if not await _add(session, post, idx, d, [_answer(d, d["text"], d["comment"])], same_row=not d["newrow"]):
        return t("err.buttons_rows", max=MAX_BUTTON_ROWS)
    d.update(n=d["n"] + 1, step=1, text="", comment="")
    await render_editor(bot, chat_id, session, state, user, post, publisher)
    await _show(bot, chat_id, state, post.id, d, resend=True)
    return None


@router.callback_query(Ed.filter(F.a == "qz_next"))
async def qz_next(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    d = _draft(await state.get_data())
    if d["step"] != 3:
        await cb.answer()
        return
    error = await _save(bot, cb.from_user.id, session, state, user, publisher, post, idx, d)
    await cb.answer(error or "", show_alert=bool(error))


@router.callback_query(Ed.filter(F.a == "qz_done"))
async def qz_done(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    await state.update_data(qz=None)
    await render_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=t("qz.saved"))


@router.message(Editor.quiz, F.text)
async def qz_input(
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
    if d["ai"] and not d["n"] and d["step"] == 1:
        await _generate(message.chat.id, bot, session, state, user, ai, settings, post, idx, d, text)
        return
    if d["step"] == 1:
        if not text or len(text) > MAX_BUTTON_TEXT:
            await message.answer(t("hc.bad_name", max=MAX_BUTTON_TEXT))
            return
        d.update(text=text, step=2)
    elif d["step"] == 2:
        if not text or len(text) > MAX_COMMENT:
            await message.answer(t("hc.too_long", max=MAX_COMMENT, n=len(text)))
            return
        d.update(comment=text, step=3)
    else:
        if len(text) > MAX_HIDDEN:
            await message.answer(t("hc.too_long", max=MAX_HIDDEN, n=len(text)))
            return
        d["locked"] = text
        error = await _save(bot, message.chat.id, session, state, user, publisher, post, idx, d)
        if error:
            await message.answer(error)
        return
    await _show(bot, message.chat.id, state, post.id, d, resend=True)


@router.message(Editor.quiz)
async def qz_wrong(message: Message) -> None:
    await message.answer(t("err.expected_input"))


async def _generate(
    chat_id: int, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    ai: AIService, settings: Settings, post: Post, idx: int, d: dict, request: str,
) -> None:
    back = markup([[btn(t("btn.back"), Ed(a="qz_back", p=post.id))]])
    primary = await take_ai(bot, chat_id, session, state, user, ai, settings, post, back)
    if primary is None:
        return
    try:
        made = await ai.quiz_buttons(
            request, post=post.parts[idx].text_html, audience=d["audience"], max_text=MAX_BUTTON_TEXT,
            max_comment=MAX_COMMENT, style=primary.ai_style_prompt,
        )
    except AIError as e:
        await limits.add(session, primary.id, "ai_text", 1)
        await show_panel(bot, chat_id, state, t(e.key), back)
        return
    analytics.track(session, user.id, "ai_call", action="quiz_buttons")
    await state.update_data(qz_made=made, qz_request=request)
    lines = [t("qz.ai_result")]
    for a in made["answers"]:
        lines += ["", f"🔘 <b>{html.escape(a['text'])}</b>", html.escape(a["comment"])]
    if made["locked"]:
        lines += ["", "🔒 " + html.escape(made["locked"])]
    kb = markup([
        [btn(t("hc.ai_apply"), Ed(a="qz_apply", p=post.id))],
        [btn(t("ai.again"), Ed(a="qz_again", p=post.id))],
        [btn(t("btn.back"), Ed(a="qz_back", p=post.id))],
    ])
    await show_panel(bot, chat_id, state, "\n".join(lines), kb)


@router.callback_query(Ed.filter(F.a == "qz_apply"))
async def qz_apply(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    data = await state.get_data()
    made = data.get("qz_made")
    if not made:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    d = {**_draft(data), "locked": made["locked"]}
    if not await _add(session, post, idx, d, [_answer(d, a["text"], a["comment"]) for a in made["answers"]], same_row=False):
        await cb.answer(t("err.buttons_rows", max=MAX_BUTTON_ROWS), show_alert=True)
        return
    await cb.answer()
    await state.update_data(qz=None, qz_made=None, qz_request=None)
    await render_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=t("qz.saved"))


@router.callback_query(Ed.filter(F.a == "qz_again"))
async def qz_again(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    ai: AIService, settings: Settings,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    data = await state.get_data()
    if not data.get("qz_request"):
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    await cb.answer()
    await _generate(cb.from_user.id, bot, session, state, user, ai, settings, post, idx, _draft(data), data["qz_request"])
