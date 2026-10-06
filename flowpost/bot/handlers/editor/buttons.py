"""Editor → «Кнопки»: what sits under the post — link buttons now, more kinds to come."""
from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.view import load_editor_post, post_from_callback, render_editor, show_panel
from flowpost.bot.keyboards.common import btn, markup
from flowpost.bot.states import Editor
from flowpost.db.models import User
from flowpost.i18n import t
from flowpost.services.parsing import MAX_BUTTON_ROWS, ParseError, buttons_to_text, parse_buttons
from flowpost.services.posts import giveaway_rows, hidden_rows, plain_buttons
from flowpost.services.publisher import Publisher

router = Router(name="editor_buttons")

# Sections of the menu that are not built yet: a tap says so instead of doing nothing.
SOON = {"btn_quiz", "btn_react", "btn_comment", "btn_fav"}


@router.callback_query(Ed.filter(F.a == "btn"))
async def ed_buttons_menu(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    part = post.parts[idx]
    typed, hidden = plain_buttons(part.buttons), hidden_rows(part.buttons)
    lines = [t("btn_menu.title"), "", t("btn_menu.pick"), t("btn_menu.or_send"), "", t("btn_menu.formats")]
    if typed or hidden:
        lines += ["", t("btn_menu.current")]
    if typed:
        lines.append(f"<code>{html.escape(buttons_to_text(typed))}</code>")
    lines += [f"🙈 {html.escape(b['text'])}" for row in hidden for b in row]
    if giveaway_rows(part.buttons):
        lines += ["", t("btn_menu.giveaway_kept")]
    if len(part.media) > 1:
        lines += ["", "ℹ️ " + t("warn.album_buttons")]
    p = post.id
    react_row = [btn(t("btn_menu.reactions"), Ed(a="btn_react", p=p)), btn(t("btn_menu.comment"), Ed(a="btn_comment", p=p))]
    if typed or hidden:  # there are buttons already: add more, or edit/delete what is there
        rows = [
            [btn(t("btn_menu.url_add"), Ed(a="btn_set", p=p))],
            [btn(t("btn_menu.quiz_add"), Ed(a="btn_quiz", p=p))],
            react_row,
            [btn(t("btn_menu.edit"), Ed(a="btn_edit", p=p)), btn(t("btn_menu.delete"), Ed(a="btn_clear", p=p))],
        ]
    else:
        rows = [
            [btn(t("btn_menu.url"), Ed(a="btn_set", p=p))],
            [btn(t("btn_menu.hidden"), Ed(a="btn_hidden", p=p)), btn(t("btn_menu.quiz"), Ed(a="btn_quiz", p=p))],
            react_row,
        ]
    rows.append([btn(t("btn.back"), Ed(a="home", p=p)), btn(t("btn_menu.favorites"), Ed(a="btn_fav", p=p))])
    kb = markup(rows)
    # buttons sent straight to the menu replace the current ones
    await state.set_state(Editor.buttons)
    await state.update_data(btn_mode="replace")
    await show_panel(bot, cb.from_user.id, state, "\n".join(lines), kb)


@router.callback_query(Ed.filter(F.a.in_({"btn_set", "btn_edit"})))
async def ed_buttons_set(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    typed = plain_buttons(post.parts[idx].buttons)
    editing = callback_data.a == "btn_edit"
    if editing and not typed:
        await cb.answer(t("btn_menu.nothing"), show_alert=True)
        return
    await cb.answer()
    await state.set_state(Editor.buttons)
    await state.update_data(btn_mode="replace" if editing else "add")
    text = t("btn_menu.prompt")
    if editing:
        text = t("btn_menu.edit_prompt") + f"\n\n<code>{html.escape(buttons_to_text(typed))}</code>"
    await show_panel(bot, cb.from_user.id, state, text, markup([[btn(t("btn.back"), Ed(a="btn", p=post.id))]]))


@router.callback_query(Ed.filter(F.a.in_(SOON)))
async def ed_buttons_soon(cb: CallbackQuery) -> None:
    await cb.answer(t("btn_menu.soon"), show_alert=True)


@router.callback_query(Ed.filter(F.a == "btn_clear"))
async def ed_buttons_clear(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    if not (plain_buttons(post.parts[idx].buttons) or hidden_rows(post.parts[idx].buttons)):
        await cb.answer(t("btn_menu.nothing"), show_alert=True)
        return
    await cb.answer(t("btn_menu.cleared"))
    post.parts[idx].buttons = giveaway_rows(post.parts[idx].buttons)
    await session.flush()
    await render_editor(bot, cb.from_user.id, session, state, user, post, publisher)


@router.message(Editor.buttons, F.text)
async def ed_buttons_input(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher
) -> None:
    post, idx = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    try:
        rows = parse_buttons(message.text or "")
    except ParseError as e:
        await message.answer(t(e.key, **e.params) + "\n\n" + t("btn_menu.example"))
        return
    part = post.parts[idx]
    if (await state.get_data()).get("btn_mode") == "add":
        rows = plain_buttons(part.buttons) + rows
    if len(rows) + len(hidden_rows(part.buttons)) > MAX_BUTTON_ROWS:
        await message.answer(t("err.buttons_rows", max=MAX_BUTTON_ROWS))
        return
    part.buttons = rows + hidden_rows(part.buttons) + giveaway_rows(part.buttons)  # those aren't typed as text
    await session.flush()
    await render_editor(bot, message.chat.id, session, state, user, post, publisher, note=t("btn_menu.saved"))


@router.message(Editor.buttons)
async def ed_buttons_wrong(message: Message) -> None:
    await message.answer(t("btn_menu.example"))
