"""Editor → «🎞 Вигляд медіа»: photos and videos under a spoiler, or sold for Telegram Stars (paid media)."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.view import load_editor_post, post_from_callback, render_editor, show_panel
from flowpost.bot.keyboards.common import btn, markup, on
from flowpost.bot.states import Editor
from flowpost.db.models import Post, User
from flowpost.i18n import t
from flowpost.services.posts import MAX_PAID_STARS, options_of, paid_ready
from flowpost.services.publisher import Publisher

router = Router(name="editor_media_view")


def view_menu(post: Post, idx: int) -> tuple[str, InlineKeyboardMarkup]:
    opts = options_of(post)
    p = post.id
    lines = [t("mv.title"), "", t("mv.help")]
    if opts["paid"] and not paid_ready(post.parts[idx].media):
        lines += ["", "⚠️ " + t("warn.paid_types")]
    rows = [[btn(on(opts["paid"]) + t("mv.paid"), Ed(a="mv_paid", p=p))]]
    if opts["paid"]:
        rows.append([btn(t("mv.price", n=opts["paid_stars"]), Ed(a="mv_price", p=p))])
    else:
        # Paid media is blurred until bought anyway, so a spoiler only applies to free media.
        rows.append([btn(on(opts["spoiler"]) + t("mv.spoiler"), Ed(a="mv_spoiler", p=p))])
    rows.append([btn(t("btn.back"), Ed(a="home", p=p))])
    return "\n".join(lines), markup(rows)


async def _refresh(bot: Bot, chat_id: int, session: AsyncSession, state: FSMContext, user: User, post: Post,
                   publisher: Publisher, idx: int) -> None:
    """Re-send the preview so it shows the change, then put the menu back under it."""
    await render_editor(bot, chat_id, session, state, user, post, publisher)
    await show_panel(bot, chat_id, state, *view_menu(post, idx))


@router.callback_query(Ed.filter(F.a.in_({"mview", "mv_paid", "mv_spoiler"})))
async def ed_media_view(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    await state.set_state(Editor.content)
    if callback_data.a == "mview":
        await show_panel(bot, cb.from_user.id, state, *view_menu(post, idx))
        return
    key = "paid" if callback_data.a == "mv_paid" else "spoiler"
    post.options = {**(post.options or {}), key: not options_of(post)[key]}
    await session.flush()
    await _refresh(bot, cb.from_user.id, session, state, user, post, publisher, idx)


@router.callback_query(Ed.filter(F.a == "mv_price"))
async def ed_media_price(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    await state.set_state(Editor.paid_price)
    await show_panel(bot, cb.from_user.id, state, t("mv.price_prompt", max=MAX_PAID_STARS),
                     markup([[btn(t("btn.back"), Ed(a="mview", p=post.id))]]))


@router.message(Editor.paid_price, F.text)
async def in_media_price(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher,
) -> None:
    post, idx = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    raw = (message.text or "").strip().replace(" ", "")
    if not raw.isdigit() or not 1 <= int(raw) <= MAX_PAID_STARS:
        await message.answer(t("mv.price_prompt", max=MAX_PAID_STARS))
        return
    post.options = {**(post.options or {}), "paid": True, "paid_stars": int(raw)}
    await session.flush()
    await state.set_state(Editor.content)
    await _refresh(bot, message.chat.id, session, state, user, post, publisher, idx)


@router.message(Editor.paid_price)
async def in_media_price_wrong(message: Message) -> None:
    await message.answer(t("mv.price_prompt", max=MAX_PAID_STARS))
