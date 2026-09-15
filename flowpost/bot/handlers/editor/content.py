"""Editor: replacing media/text by sending new content, navigation between parts."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.create_post import extract_content
from flowpost.bot.handlers.editor.view import load_editor_post, post_from_callback, render_editor
from flowpost.bot.states import Editor
from flowpost.db.models import User
from flowpost.i18n import t
from flowpost.services.html_sanitize import visible_len
from flowpost.services.posts import TEXT_LIMIT, group_error
from flowpost.services.publisher import Publisher

router = Router(name="editor_content")
CONTENT = F.photo | F.video | F.animation | F.document | F.audio | F.text


@router.callback_query(Ed.filter(F.a == "noop"))
async def ed_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(Ed.filter(F.a == "home"))
async def ed_home(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    await render_editor(bot, cb.from_user.id, session, state, user, post, publisher)


@router.callback_query(Ed.filter(F.a == "part"))
async def ed_part(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    index = int(callback_data.v) if callback_data.v.isdigit() else 0
    await state.update_data(part=max(0, min(index, len(post.parts) - 1)))
    await render_editor(bot, cb.from_user.id, session, state, user, post, publisher)


@router.callback_query(Ed.filter(F.a == "del_text"))
async def ed_delete_text(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    post.parts[idx].text_html = ""
    await session.flush()
    await cb.answer()
    await render_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=t("ed.deleted_text"))


@router.callback_query(Ed.filter(F.a == "del_sig"))
async def ed_delete_source_signature(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    post.parts[idx].source_signature = ""
    await session.flush()
    await cb.answer()
    await render_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=t("ed.deleted_source_signature"))


@router.message(Editor.content, CONTENT)
async def ed_replace_content(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    state: FSMContext,
    user: User,
    publisher: Publisher,
    album: list[Message] | None = None,
) -> None:
    if message.text and message.text.startswith("/"):
        await message.answer(t("err.unknown_command"))
        return
    post, idx = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    part = post.parts[idx]
    text, media, source_signature = extract_content(album or [message])
    if visible_len(text) > TEXT_LIMIT:
        await message.answer(t("err.text_too_long", max=TEXT_LIMIT))
        return
    if media:
        error = group_error(media)
        if error:
            await message.answer(t(error))
            return
        part.media = media
        if text:
            part.text_html = text
            part.source_signature = source_signature
        note = t("ed.updated_media")
    else:
        part.text_html = text
        part.source_signature = source_signature
        note = t("ed.updated_text")
    await session.flush()
    await render_editor(bot, message.chat.id, session, state, user, post, publisher, note=note)


@router.message(Editor.content)
async def ed_unsupported(message: Message) -> None:
    await message.answer(t("err.unsupported_content"))
