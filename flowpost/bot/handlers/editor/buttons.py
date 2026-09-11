"""Editor → «Кнопки»: inline URL buttons under the post."""
from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.view import load_editor_post, post_from_callback, render_editor, show_panel
from flowpost.bot.keyboards.common import btn, markup
from flowpost.bot.keyboards.editor import back_kb
from flowpost.bot.states import Editor
from flowpost.db.models import User
from flowpost.i18n import t
from flowpost.services.parsing import ParseError, buttons_to_text, parse_buttons
from flowpost.services.publisher import Publisher

router = Router(name="editor_buttons")


@router.callback_query(Ed.filter(F.a == "btn"))
async def ed_buttons_menu(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    part = post.parts[idx]
    current = html.escape(buttons_to_text(part.buttons)) if part.buttons else t("btn_menu.none")
    lines = [t("btn_menu.title"), "", t("btn_menu.current"), f"<code>{current}</code>" if part.buttons else current]
    if len(part.media) > 1:
        lines += ["", "ℹ️ " + t("warn.album_buttons")]
    lines += ["", t("btn_menu.help")]
    p = post.id
    kb = markup([
        [btn(t("btn_menu.set"), Ed(a="btn_set", p=p))],
        [btn(t("btn_menu.clear"), Ed(a="btn_clear", p=p))] if part.buttons else [],
        [btn(t("btn.back"), Ed(a="home", p=p))],
    ])
    await show_panel(bot, cb.from_user.id, state, "\n".join(lines), kb)


@router.callback_query(Ed.filter(F.a == "btn_set"))
async def ed_buttons_set(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    await state.set_state(Editor.buttons)
    await show_panel(bot, cb.from_user.id, state, t("btn_menu.prompt"), back_kb(post.id))


@router.callback_query(Ed.filter(F.a == "btn_clear"))
async def ed_buttons_clear(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer(t("btn_menu.cleared"))
    post.parts[idx].buttons = []
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
    post.parts[idx].buttons = rows
    await session.flush()
    await render_editor(bot, message.chat.id, session, state, user, post, publisher, note=t("btn_menu.saved"))


@router.message(Editor.buttons)
async def ed_buttons_wrong(message: Message) -> None:
    await message.answer(t("btn_menu.example"))
