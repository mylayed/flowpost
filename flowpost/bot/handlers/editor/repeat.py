"""Editor → «Автоповтор»: periodic re-publication of the same post."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.view import (
    fmt_interval,
    load_editor_post,
    post_from_callback,
    render_editor,
    show_panel,
)
from flowpost.bot.keyboards.common import btn, markup, on
from flowpost.bot.states import Editor
from flowpost.db.models import Post, RepeatRule, User
from flowpost.i18n import t
from flowpost.services.parsing import ParseError, parse_positive_int
from flowpost.services.publisher import Publisher

router = Router(name="editor_repeat")

INTERVALS = [1440, 4320, 10080]
COUNTS: list[int | None] = [None, 3, 5, 10]
MAX_REPEAT_HOURS = 24 * 90


def repeat_menu(post: Post) -> tuple[str, object]:
    rule = post.repeat
    active = bool(rule and rule.active)
    p = post.id
    lines = [t("rep.title"), ""]
    if active:
        count = t("rep.infinite") if rule.remaining_count is None else t("rep.times", n=rule.remaining_count)
        lines.append(t("rep.current", interval=fmt_interval(rule.interval_minutes), count=count))
        if rule.delete_previous:
            lines.append(t("rep.deletes_previous"))
    else:
        lines.append(t("rep.off"))
    lines += ["", t("rep.help")]
    rows = [
        [btn(on(active and rule.interval_minutes == m) + fmt_interval(m), Ed(a="rp_i", p=p, v=str(m))) for m in INTERVALS],
        [btn(t("rep.custom"), Ed(a="rp_custom", p=p))],
        [btn(on(active and rule.remaining_count == c) + (t("rep.inf_short") if c is None else f"{c}×"),
             Ed(a="rp_c", p=p, v="inf" if c is None else str(c))) for c in COUNTS],
        [btn(on(bool(rule and rule.delete_previous)) + t("rep.delete_prev"), Ed(a="rp_dp", p=p))],
    ]
    if active:
        rows.append([btn(t("rep.disable"), Ed(a="rp_off", p=p))])
    rows.append([btn(t("btn.back"), Ed(a="home", p=p))])
    return "\n".join(lines), markup(rows)


def _ensure_rule(post: Post) -> RepeatRule:
    if post.repeat is None:
        post.repeat = RepeatRule(post_id=post.id, interval_minutes=1440, remaining_count=None, delete_previous=False, active=True)
    return post.repeat


@router.callback_query(Ed.filter(F.a.in_({"rep", "rp_i", "rp_c", "rp_dp", "rp_off"})))
async def ed_repeat(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    a, v = callback_data.a, callback_data.v
    if a == "rp_i" and v.isdigit():
        rule = _ensure_rule(post)
        rule.interval_minutes = int(v)
        rule.active = True
    elif a == "rp_c":
        rule = _ensure_rule(post)
        rule.remaining_count = None if v == "inf" else int(v)
        rule.active = True
    elif a == "rp_dp":
        rule = _ensure_rule(post)
        rule.delete_previous = not rule.delete_previous
    elif a == "rp_off" and post.repeat is not None:
        post.repeat.active = False
    await session.flush()
    await cb.answer()
    await state.set_state(Editor.content)
    text, kb = repeat_menu(post)
    await show_panel(bot, cb.from_user.id, state, text, kb)


@router.callback_query(Ed.filter(F.a == "rp_custom"))
async def ed_repeat_custom(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    await state.set_state(Editor.repeat_hours)
    back = markup([[btn(t("btn.back"), Ed(a="rep", p=post.id))]])
    await show_panel(bot, cb.from_user.id, state, t("rep.custom_prompt", max=MAX_REPEAT_HOURS), back)


@router.message(Editor.repeat_hours, F.text)
async def in_repeat_hours(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher
) -> None:
    post, _ = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    try:
        hours = parse_positive_int(message.text or "", MAX_REPEAT_HOURS)
    except ParseError as e:
        await message.answer(t(e.key, **e.params))
        return
    rule = _ensure_rule(post)
    rule.interval_minutes = hours * 60
    rule.active = True
    await session.flush()
    await render_editor(
        bot, message.chat.id, session, state, user, post, publisher,
        note="✅ " + t("ed.sum_repeat", interval=fmt_interval(rule.interval_minutes)),
    )
