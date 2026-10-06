"""Editor → «Кнопки» → «Реакції»: a row of reaction buttons with counters under the post. Picked from a grid of
emoji one by one, or sent as text: «👍 / 👎», «Так / Ні». A post part has one set of them."""
from __future__ import annotations

import html
import secrets

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.hidden_buttons import COLORS, color_kb
from flowpost.bot.handlers.editor.view import load_editor_post, post_from_callback, render_editor, show_panel
from flowpost.bot.keyboards.common import btn, chunked, markup
from flowpost.bot.states import Editor
from flowpost.db.models import Post, User
from flowpost.i18n import t
from flowpost.services.parsing import MAX_BUTTON_ROWS, MAX_REACTIONS_PER_ROW, ParseError, parse_reactions
from flowpost.services.posts import bot_rows, giveaway_rows, plain_buttons, react_rows
from flowpost.services.publisher import Publisher

router = Router(name="editor_react_buttons")

EMOJI = (
    "👍", "👎", "❤️", "🔥", "🥰",
    "👏", "😁", "🤔", "😔", "😱",
    "😌", "🎉", "🤯", "🙏", "👌",
    "😍", "🤣", "💯", "🏆", "💔",
    "🤨", "👀", "😭", "🤡", "🗿",
)


def set_reactions(post: Post, idx: int, rows: list[list[str]], style: str | None) -> bool:
    """Replace the part's reaction buttons with `rows` of texts, where the old ones stood (or after the other bot
    buttons); False when that's more rows than Telegram allows. Keeps the ids of reactions that stay."""
    part = post.parts[idx]
    old = {b["text"]: b for row in react_rows(part.buttons) for b in row}
    group = next(iter(old.values()))["react"] if old else secrets.token_hex(3)
    new = [[{
        "text": text, "hid": old[text]["hid"] if text in old else secrets.token_hex(3), "react": group,
        **({"style": style} if style else {}),
    } for text in row] for row in rows]
    others = bot_rows(part.buttons)
    at = next((i for i, row in enumerate(others) if any("react" in b for b in row)), len(others))
    kept = [row for row in ([b for b in r if "react" not in b] for r in others) if row]
    at = min(at, len(kept))
    rows_out = plain_buttons(part.buttons) + kept[:at] + new + kept[at:]
    if len(rows_out) > MAX_BUTTON_ROWS:
        return False
    part.buttons = rows_out + giveaway_rows(part.buttons)
    return True


def _current(post: Post, idx: int) -> tuple[list[list[str]], str | None]:
    rows = react_rows(post.parts[idx].buttons)
    return [[b["text"] for b in row] for row in rows], next((b.get("style") for row in rows for b in row), None)


def _screen(post: Post, idx: int) -> tuple[str, object]:
    p = post.id
    rows, style = _current(post, idx)
    chosen = {text for row in rows for text in row}
    text = t("rc.title")
    if rows:
        text += "\n\n" + t("rc.current") + "\n" + "\n".join(html.escape(" / ".join(row)) for row in rows)
    grid = [
        btn(("✓" if e in chosen else "") + e, Ed(a="rc_t", p=p, v=str(i)), style if e in chosen else None)
        for i, e in enumerate(EMOJI)
    ]
    kb = [[btn(t("rc.color", color=t(f"hc.color_{style or 'none'}")), Ed(a="rc_color", p=p))], *chunked(grid, 5)]
    if rows:
        kb.append([btn(t("rc.clear"), Ed(a="rc_clear", p=p)), btn(t("rc.done"), Ed(a="home", p=p))])
    kb.append([btn(t("btn.back"), Ed(a="btn", p=p))])
    return text, markup(kb)


async def _show(bot: Bot, chat_id: int, state: FSMContext, post: Post, idx: int, *, resend: bool = False) -> None:
    await state.set_state(Editor.reactions)
    text, kb = _screen(post, idx)
    await show_panel(bot, chat_id, state, text, kb, resend=resend)


@router.callback_query(Ed.filter(F.a.in_({"btn_react", "rc_back"})))
async def rc_menu(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    await _show(bot, cb.from_user.id, state, post, idx)


@router.callback_query(Ed.filter(F.a == "rc_t"))
async def rc_toggle(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None or not callback_data.v.isdigit() or int(callback_data.v) >= len(EMOJI):
        return
    emoji = EMOJI[int(callback_data.v)]
    rows, style = _current(post, idx)
    style = style or (await state.get_data()).get("rc_style")
    if any(emoji in row for row in rows):
        rows = [row for row in ([e for e in r if e != emoji] for r in rows) if row]
    elif rows and len(rows[-1]) < MAX_REACTIONS_PER_ROW:
        rows[-1].append(emoji)
    else:
        rows.append([emoji])
    if not set_reactions(post, idx, rows, style):
        await cb.answer(t("err.buttons_rows", max=MAX_BUTTON_ROWS), show_alert=True)
        return
    await cb.answer()
    await session.flush()
    await _show(bot, cb.from_user.id, state, post, idx)


@router.callback_query(Ed.filter(F.a == "rc_color"))
async def rc_color(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    rows, style = _current(post, idx)
    if callback_data.v in COLORS:  # picked: recolour the reactions there are and the ones to come
        style = None if callback_data.v == "none" else callback_data.v
        await state.update_data(rc_style=style)
        if rows:
            set_reactions(post, idx, rows, style)
            await session.flush()
        await _show(bot, cb.from_user.id, state, post, idx)
        return
    style = style or (await state.get_data()).get("rc_style")
    await show_panel(bot, cb.from_user.id, state, t("hc.color_title"), color_kb(post.id, style, "rc_color", "rc_back"))


@router.callback_query(Ed.filter(F.a == "rc_clear"))
async def rc_clear(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer(t("rc.cleared"))
    set_reactions(post, idx, [], None)
    await session.flush()
    await _show(bot, cb.from_user.id, state, post, idx)


async def save_typed(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher,
    post: Post, idx: int,
) -> None:
    """Reactions sent as text, here or straight to the «Кнопки» menu."""
    try:
        rows = parse_reactions(message.text or "")
    except ParseError as e:
        await message.answer(t(e.key, **e.params) + "\n\n" + t("rc.example"))
        return
    style = _current(post, idx)[1] or (await state.get_data()).get("rc_style")
    if not set_reactions(post, idx, rows, style):
        await message.answer(t("err.buttons_rows", max=MAX_BUTTON_ROWS))
        return
    await session.flush()
    await render_editor(bot, message.chat.id, session, state, user, post, publisher, note=t("rc.saved"))


@router.message(Editor.reactions, F.text)
async def rc_input(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher
) -> None:
    post, idx = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    await save_typed(message, bot, session, state, user, publisher, post, idx)


@router.message(Editor.reactions)
async def rc_wrong(message: Message) -> None:
    await message.answer(t("rc.example"))
