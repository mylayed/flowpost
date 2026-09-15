"""Editor → «Медіа»: managing photos/videos of the current part (media group)."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.create_post import extract_content
from flowpost.bot.handlers.editor.view import load_editor_post, post_from_callback, render_editor, show_panel
from flowpost.bot.keyboards.common import btn, markup
from flowpost.bot.states import Editor
from flowpost.db.models import Post, User
from flowpost.i18n import t
from flowpost.services.posts import MAX_MEDIA, group_error, media_icon
from flowpost.services.publisher import Publisher

router = Router(name="editor_media")
MEDIA = F.photo | F.video | F.animation | F.document | F.audio


def media_menu(post: Post, idx: int, note: str | None = None) -> tuple[str, object]:
    part = post.parts[idx]
    p = post.id
    lines = [t("media_menu.title", n=len(part.media), max=MAX_MEDIA)]
    if part.media:
        lines += [f"{i}. {media_icon(m)} {t('media.' + m['type'])}" for i, m in enumerate(part.media, start=1)]
    else:
        lines.append(t("media_menu.empty"))
    lines += ["", t("media_menu.help")]
    if note:
        lines += ["", note]
    rows = []
    for i, m in enumerate(part.media):
        row = [btn(f"{i + 1}. {media_icon(m)}", Ed(a="noop", p=p))]
        if i > 0:
            row.append(btn("⬆️", Ed(a="m_up", p=p, v=str(i))))
        if i < len(part.media) - 1:
            row.append(btn("⬇️", Ed(a="m_down", p=p, v=str(i))))
        row.append(btn("🗑", Ed(a="m_del", p=p, v=str(i))))
        rows.append(row)
    if len(part.media) < MAX_MEDIA:
        rows.append([btn(t("media_menu.add"), Ed(a="m_add", p=p))])
    if part.media:
        rows.append([btn(t("media_menu.clear"), Ed(a="m_clear", p=p))])
    rows.append([btn(t("btn.back"), Ed(a="home", p=p))])
    return "\n".join(lines), markup(rows)


@router.callback_query(Ed.filter(F.a == "media"))
async def ed_media_menu(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    await state.set_state(Editor.content)
    text, kb = media_menu(post, idx)
    await show_panel(bot, cb.from_user.id, state, text, kb)


@router.callback_query(Ed.filter(F.a.in_({"m_up", "m_down", "m_del", "m_clear"})))
async def ed_media_change(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    part = post.parts[idx]
    items = list(part.media)
    i = int(callback_data.v) if callback_data.v.isdigit() else -1
    if callback_data.a == "m_clear":
        items = []
    elif 0 <= i < len(items):
        if callback_data.a == "m_del":
            items.pop(i)
        elif callback_data.a == "m_up" and i > 0:
            items[i - 1], items[i] = items[i], items[i - 1]
        elif callback_data.a == "m_down" and i < len(items) - 1:
            items[i + 1], items[i] = items[i], items[i + 1]
    part.media = items
    await session.flush()
    await cb.answer(t("media_menu.changed"))
    text, kb = media_menu(post, idx, note=t("media_menu.back_to_preview"))
    await show_panel(bot, cb.from_user.id, state, text, kb)


@router.callback_query(Ed.filter(F.a == "m_add"))
async def ed_media_add(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    await state.set_state(Editor.add_media)
    kb = markup([[btn(t("media_menu.done"), Ed(a="m_done", p=post.id))]])
    await show_panel(bot, cb.from_user.id, state, t("media_menu.add_prompt"), kb)


@router.callback_query(Ed.filter(F.a == "m_done"))
async def ed_media_done(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    await render_editor(bot, cb.from_user.id, session, state, user, post, publisher)


@router.message(Editor.add_media, MEDIA)
async def ed_media_received(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    state: FSMContext,
    user: User,
    album: list[Message] | None = None,
) -> None:
    post, idx = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    part = post.parts[idx]
    _, media, _ = extract_content(album or [message])
    combined = list(part.media) + media
    error = group_error(combined)
    if error:
        await message.answer(t(error))
        return
    part.media = combined
    await session.flush()
    kb = markup([[btn(t("media_menu.done"), Ed(a="m_done", p=post.id))]])
    await show_panel(
        bot, message.chat.id, state, t("media_menu.added", n=len(combined), max=MAX_MEDIA), kb, resend=True
    )


@router.message(Editor.add_media)
async def ed_media_wrong(message: Message) -> None:
    await message.answer(t("media_menu.add_prompt"))
