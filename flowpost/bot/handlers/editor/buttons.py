"""Editor → «Кнопки»: what sits under the post — link buttons, «Залишити коментар», and the menu of the other
kinds (hidden continuation, quiz, reactions)."""
from __future__ import annotations

import html
import secrets

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
from flowpost.services.parsing import (
    MAX_BUTTON_ROWS, MAX_BUTTON_TEXT, MAX_HINT, SEPARATOR, ParseError, buttons_to_text, looks_like_reactions,
    normalize_url, parse_buttons,
)
from flowpost.services.posts import bot_rows, giveaway_rows, has_comment_button, plain_buttons, react_rows
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


def removable(buttons: list[list[dict]] | None) -> list[tuple[str, str]]:
    """What «Видалити» lists, as (key, label): each link button and hidden continuation on its own, a quiz and the
    reactions as a whole set, «Залишити коментар». The giveaway's button belongs to the giveaway and isn't listed."""
    items: list[tuple[str, str]] = []
    for r, row in enumerate(plain_buttons(buttons)):
        items += [(f"u{r}_{c}", ("💡 " if "hint" in b else "🔗 ") + b["text"]) for c, b in enumerate(row)]
    quizzes: dict[str, list[str]] = {}
    for row in bot_rows(buttons):
        for b in row:
            if "hidden" in b:
                items.append((f"h{b['hid']}", "🙈 " + b["text"]))
            elif "quiz" in b:
                if b["quiz"] not in quizzes:
                    quizzes[b["quiz"]] = []
                    items.append((f"q{b['quiz']}", ""))
                quizzes[b["quiz"]].append(b["text"])
            elif "comment" in b:
                items.append(("c", b["text"]))
        if row and "react" in row[0] and not any(k == "r" for k, _ in items):
            items.append(("r", " / ".join(b["text"] for row_ in react_rows(buttons) for b in row_)))
    return [(k, "❓ " + " | ".join(quizzes[k[1:]]) if k.startswith("q") else label) for k, label in items]


def remove_button(buttons: list[list[dict]], key: str) -> list[list[dict]]:
    if key.startswith("u"):
        r, _, c = key[1:].partition("_")
        links = [list(row) for row in plain_buttons(buttons)]
        if r.isdigit() and c.isdigit() and int(r) < len(links) and int(c) < len(links[int(r)]):
            links[int(r)].pop(int(c))
        return [row for row in links if row] + bot_rows(buttons) + giveaway_rows(buttons)

    def gone(b: dict) -> bool:
        return (
            (key.startswith("h") and b.get("hid") == key[1:]) or (key.startswith("q") and b.get("quiz") == key[1:])
            or (key == "r" and "react" in b) or (key == "c" and "comment" in b)
        )
    return [row for row in ([b for b in r if not gone(b)] for r in buttons) if row]


async def _show_remove(bot: Bot, chat_id: int, state: FSMContext, post: Post, idx: int) -> None:
    p = post.id
    rows = [[btn(label[:60], Ed(a="btn_rm", p=p, v=key))] for key, label in removable(post.parts[idx].buttons)]
    rows += [[btn(t("btn_menu.delete_all"), Ed(a="btn_clear_all", p=p))], [btn(t("btn.back"), Ed(a="btn", p=p))]]
    await show_panel(bot, chat_id, state, t("btn_menu.pick_delete"), markup(rows))


@router.callback_query(Ed.filter(F.a.in_({"btn_clear", "btn_rm"})))
async def ed_buttons_remove(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    """«Видалити»: the buttons under the post one by one; a tap removes that one."""
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    part = post.parts[idx]
    if callback_data.a == "btn_rm":
        part.buttons = remove_button(part.buttons or [], callback_data.v)
        await session.flush()
        await cb.answer(t("btn_menu.removed"))
    elif not removable(part.buttons):
        await cb.answer(t("btn_menu.nothing"), show_alert=True)
        return
    else:
        await cb.answer()
    if removable(part.buttons):
        await _show_remove(bot, cb.from_user.id, state, post, idx)
    else:
        await _show_menu(bot, cb.from_user.id, state, post, idx)


@router.callback_query(Ed.filter(F.a == "btn_clear_all"))
async def ed_buttons_clear(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
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
    raw = (message.text or "").strip()
    if is_hint_name(raw):  # just a name: the hint's text comes next
        await state.set_state(Editor.hint)
        await state.update_data(hint_name=raw)
        p = post.id
        await message.answer(t("btn_menu.hint_prompt", name=html.escape(raw), max=MAX_HINT),
                             reply_markup=markup([[btn(t("btn.back"), Ed(a="btn", p=p))]]))
        return
    try:
        rows = parse_buttons(raw, hints=True)
    except ParseError as e:
        await message.answer(t(e.key, **e.params) + "\n\n" + t("btn_menu.example"))
        return
    await _save_typed(message, bot, session, state, user, publisher, post, idx, rows, add=data.get("btn_mode") == "add")


def is_hint_name(raw: str) -> bool:
    """One line with no link or «Текст — …» in it: the name of a hint button («👉 Читати далі»)."""
    return (
        0 < len(raw) <= MAX_BUTTON_TEXT and "\n" not in raw and "|" not in raw and not SEPARATOR.search(raw)
        and normalize_url(raw) is None and not raw.startswith("@")
    )


async def _save_typed(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher,
    post: Post, idx: int, rows: list[list[dict]], *, add: bool,
) -> None:
    part = post.parts[idx]
    if add:
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


@router.message(Editor.hint, F.text)
async def ed_hint_text(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher
) -> None:
    """The text of a hint button whose name came on its own; the button joins the others under the post."""
    post, idx = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    text, name = (message.text or "").strip(), (await state.get_data()).get("hint_name") or ""
    if not name or not text or len(text) > MAX_HINT:
        await message.answer(t("hc.too_long", max=MAX_HINT, n=len(text)))
        return
    row = [{"text": name, "hint": text, "hid": secrets.token_hex(3)}]
    await _save_typed(message, bot, session, state, user, publisher, post, idx, [row], add=True)


@router.message(Editor.hint)
async def ed_hint_wrong(message: Message) -> None:
    await message.answer(t("err.expected_input"))
