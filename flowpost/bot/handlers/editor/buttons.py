"""Editor → «Кнопки»: what sits under the post — link buttons, «Залишити коментар», and the menu of the other
kinds (hidden continuation, quiz, reactions)."""
from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.react_buttons import save_typed as save_reactions
from flowpost.bot.handlers.editor.view import load_editor_post, post_from_callback, render_editor, show_panel
from flowpost.bot.keyboards.common import btn, markup
from flowpost.bot.states import Editor
from flowpost.db.models import Post, User
from flowpost.db.repo import channels as channels_repo
from flowpost.i18n import t
from flowpost.services.parsing import MAX_BUTTON_ROWS, ParseError, buttons_to_text, looks_like_reactions, parse_buttons
from flowpost.services.posts import bot_rows, giveaway_rows, has_comment_button, plain_buttons
from flowpost.services.publisher import Publisher

router = Router(name="editor_buttons")

EXTRA_ICONS = {"hidden": "🙈 ", "quiz": "❓ ", "comment": "💬 "}


def buttons_menu(post: Post, idx: int) -> tuple[str, object]:
    part = post.parts[idx]
    typed, extra = plain_buttons(part.buttons), bot_rows(part.buttons)
    lines = [t("btn_menu.title"), "", t("btn_menu.pick"), t("btn_menu.or_send"), "", t("btn_menu.formats")]
    if typed or extra:
        lines += ["", t("btn_menu.current")]
    if typed:
        lines.append(f"<code>{html.escape(buttons_to_text(typed))}</code>")
    for row in extra:
        if "react" in row[0]:
            lines.append(html.escape(" / ".join(b["text"] for b in row)))
        else:
            lines += [EXTRA_ICONS[next(k for k in EXTRA_ICONS if k in b)] + html.escape(b["text"]) for b in row]
    if giveaway_rows(part.buttons):
        lines += ["", t("btn_menu.giveaway_kept")]
    if len(part.media) > 1:
        lines += ["", "ℹ️ " + t("warn.album_buttons")]
    p = post.id
    comment = ("✔ " if has_comment_button(part.buttons) else "") + t("btn_menu.comment")
    rows = [
        [btn(t("btn_menu.url_add") if typed or extra else t("btn_menu.url"), Ed(a="btn_set", p=p))],
        [btn(t("btn_menu.hidden"), Ed(a="btn_hidden", p=p)), btn(t("btn_menu.quiz"), Ed(a="btn_quiz", p=p))],
        [btn(t("btn_menu.reactions"), Ed(a="btn_react", p=p)), btn(comment, Ed(a="btn_comment", p=p))],
    ]
    if typed or extra:  # there are buttons already: edit or delete them too
        rows.append([btn(t("btn_menu.edit"), Ed(a="btn_edit", p=p)), btn(t("btn_menu.delete"), Ed(a="btn_clear", p=p))])
    rows.append([btn(t("btn.back"), Ed(a="home", p=p)), btn(t("btn_menu.favorites"), Ed(a="btn_fav", p=p))])
    return "\n".join(lines), markup(rows)


async def _show_menu(bot: Bot, chat_id: int, state: FSMContext, post: Post, idx: int) -> None:
    # buttons sent straight to the menu replace the current ones
    await state.set_state(Editor.buttons)
    await state.update_data(btn_mode="replace", btn_editing=False)
    text, kb = buttons_menu(post, idx)
    await show_panel(bot, chat_id, state, text, kb)


@router.callback_query(Ed.filter(F.a == "btn"))
async def ed_buttons_menu(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    await _show_menu(bot, cb.from_user.id, state, post, idx)


@router.callback_query(Ed.filter(F.a == "btn_comment"))
async def ed_buttons_comment(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    """«Залишити коментар»: a button under the post that opens its comments; a tap switches it on and off."""
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    part = post.parts[idx]
    if has_comment_button(part.buttons):
        part.buttons = [row for row in ([b for b in r if "comment" not in b] for r in part.buttons) if row]
        await cb.answer(t("cm.off"))
    else:
        if len(plain_buttons(part.buttons)) + len(bot_rows(part.buttons)) >= MAX_BUTTON_ROWS:
            await cb.answer(t("err.buttons_rows", max=MAX_BUTTON_ROWS), show_alert=True)
            return
        part.buttons = (
            plain_buttons(part.buttons) + bot_rows(part.buttons)
            + [[{"text": t("cm.btn"), "comment": True}]] + giveaway_rows(part.buttons)
        )
        channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
        if any(c.kind == "channel" and not c.discussion_chat_id for c in channels):
            await cb.answer(t("cm.no_discussion"), show_alert=True)
        else:
            await cb.answer(t("cm.on"))
    await session.flush()
    await _show_menu(bot, cb.from_user.id, state, post, idx)


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
    await state.update_data(btn_mode="replace" if editing else "add", btn_editing=editing)
    text = t("btn_menu.prompt")
    if editing:
        text = t("btn_menu.edit_prompt") + f"\n\n<code>{html.escape(buttons_to_text(typed))}</code>"
    await show_panel(bot, cb.from_user.id, state, text, markup([[btn(t("btn.back"), Ed(a="btn", p=post.id))]]))


@router.callback_query(Ed.filter(F.a == "btn_clear"))
async def ed_buttons_clear(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    if not (plain_buttons(post.parts[idx].buttons) or bot_rows(post.parts[idx].buttons)):
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
    data = await state.get_data()
    if data.get("btn_mode") == "replace" and not data.get("btn_editing") and looks_like_reactions(message.text or ""):
        await save_reactions(message, bot, session, state, user, publisher, post, idx)
        return
    try:
        rows = parse_buttons(message.text or "")
    except ParseError as e:
        await message.answer(t(e.key, **e.params) + "\n\n" + t("btn_menu.example"))
        return
    part = post.parts[idx]
    if data.get("btn_mode") == "add":
        rows = plain_buttons(part.buttons) + rows
    if len(rows) + len(bot_rows(part.buttons)) > MAX_BUTTON_ROWS:
        await message.answer(t("err.buttons_rows", max=MAX_BUTTON_ROWS))
        return
    part.buttons = rows + bot_rows(part.buttons) + giveaway_rows(part.buttons)  # those aren't typed as text
    await session.flush()
    await render_editor(bot, message.chat.id, session, state, user, post, publisher, note=t("btn_menu.saved"))


@router.message(Editor.buttons)
async def ed_buttons_wrong(message: Message) -> None:
    await message.answer(t("btn_menu.example"))
