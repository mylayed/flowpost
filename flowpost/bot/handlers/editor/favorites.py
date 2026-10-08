"""Editor → «Кнопки» → «Обране»: the owner's own set of buttons. Saved from one post's buttons, each row goes under
another post in one tap. A row is kept as it is — a link, a hidden continuation, the reactions, «Залишити
коментар» — without its ids; quiz answers belong to their quiz and the giveaway button to its giveaway, so
those aren't saved."""
from __future__ import annotations

import secrets

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.react_buttons import set_reactions
from flowpost.bot.handlers.editor.view import post_from_callback, show_panel
from flowpost.bot.keyboards.common import btn, markup
from flowpost.db.models import Post, User
from flowpost.i18n import t
from flowpost.services.parsing import MAX_BUTTON_ROWS
from flowpost.services.posts import bot_rows, drop_signature, giveaway_rows, has_comment_button, plain_buttons

router = Router(name="editor_favorites")

MAX_FAVORITES = 20


def _clean(row: list[dict]) -> list[dict]:
    return [{k: v for k, v in b.items() if k != "hid"} for b in row]


def _savable(post: Post, idx: int) -> list[list[dict]]:
    part = post.parts[idx]
    rows = plain_buttons(part.buttons) + bot_rows(part.buttons)
    return [_clean(row) for row in ([b for b in r if "quiz" not in b] for r in rows) if row]


def _label(row: list[dict]) -> str:
    text = " / " if "react" in row[0] else " | "
    return text.join(b["text"] for b in row)[:60]


def _screen(user: User, post_id: int) -> tuple[str, object]:
    p = post_id
    rows = [[btn("➕ " + _label(row), Ed(a="fv_use", p=p, v=str(i)))] for i, row in enumerate(user.favorite_buttons or [])]
    if user.favorite_buttons:
        rows.append([btn(t("fv.delete"), Ed(a="fv_del", p=p))])
    rows += [[btn(t("fv.save"), Ed(a="fv_save", p=p))], [btn(t("btn.back"), Ed(a="btn", p=p))]]
    text = t("fv.title") + "\n\n" + t("fv.help")
    if user.favorite_buttons:
        text += "\n\n" + t("fv.use_help")
    return text, markup(rows)


@router.callback_query(Ed.filter(F.a == "btn_fav"))
async def fv_menu(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    text, kb = _screen(user, post.id)
    await show_panel(bot, cb.from_user.id, state, text, kb)


@router.callback_query(Ed.filter(F.a == "fv_save"))
async def fv_save(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    saved = list(user.favorite_buttons or [])
    new = [row for row in _savable(post, idx) if row not in saved]
    if not _savable(post, idx):
        await cb.answer(t("fv.nothing"), show_alert=True)
        return
    if len(saved) + len(new) > MAX_FAVORITES:
        await cb.answer(t("fv.full", max=MAX_FAVORITES), show_alert=True)
        return
    user.favorite_buttons = saved + new
    await session.flush()
    await cb.answer(t("fv.saved"), show_alert=True)
    text, kb = _screen(user, post.id)
    await show_panel(bot, cb.from_user.id, state, text, kb)


@router.callback_query(Ed.filter(F.a == "fv_use"))
async def fv_use(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    favorites = user.favorite_buttons or []
    i = int(callback_data.v) if callback_data.v.isdigit() else -1
    if not 0 <= i < len(favorites):
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    row = [{**b, "hid": secrets.token_hex(3)} if "hidden" in b or "hint" in b else dict(b) for b in favorites[i]]
    part = post.parts[idx]
    signature_dropped = False
    links, extra, giveaway = plain_buttons(part.buttons), bot_rows(part.buttons), giveaway_rows(part.buttons)
    if "react" in row[0]:  # one set of reactions per post: this one takes the place of the old
        ok = set_reactions(post, idx, [[b["text"] for b in row]], row[0].get("style"))
    elif "comment" in row[0] and has_comment_button(part.buttons):
        await cb.answer(t("fv.already"))
        return
    else:
        rows = links + [row] + extra if row[0].keys() & {"url", "hint"} else links + extra + [row]
        ok = len(rows) <= MAX_BUTTON_ROWS
        if ok:
            part.buttons = rows + giveaway
            signature_dropped = "url" in row[0] and drop_signature(post)
    if not ok:
        await cb.answer(t("err.buttons_rows", max=MAX_BUTTON_ROWS), show_alert=True)
        return
    await session.flush()
    note = t("fv.added", text=_label(row))
    if signature_dropped:
        note += "\n" + t("ed.signature_off_buttons")
    await cb.answer(note, show_alert=signature_dropped)


@router.callback_query(Ed.filter(F.a.in_({"fv_del", "fv_rm"})))
async def fv_delete(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    favorites = list(user.favorite_buttons or [])
    if callback_data.a == "fv_rm" and callback_data.v.isdigit() and int(callback_data.v) < len(favorites):
        favorites.pop(int(callback_data.v))
        user.favorite_buttons = favorites
        await session.flush()
        await cb.answer(t("fv.removed"))
    else:
        await cb.answer()
    if not favorites:
        text, kb = _screen(user, post.id)
        await show_panel(bot, cb.from_user.id, state, text, kb)
        return
    rows = [[btn(_label(row), Ed(a="fv_rm", p=post.id, v=str(i)))] for i, row in enumerate(favorites)]
    rows.append([btn(t("btn.back"), Ed(a="btn_fav", p=post.id))])
    await show_panel(bot, cb.from_user.id, state, t("fv.pick_delete"), markup(rows))
