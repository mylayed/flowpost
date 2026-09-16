"""Starting a new post: via the menu button or by simply sending content to the bot."""
from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Fd, Nc
from flowpost.bot.handlers.editor.view import open_editor, safe_delete
from flowpost.bot.keyboards.common import add_channel_inline_kb
from flowpost.bot.keyboards.editor import channels_pick_kb
from flowpost.bot.states import FolderInput
from flowpost.db.models import Channel, User
from flowpost.db.repo import channel_admins as channel_admins_repo
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import folders as folders_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.i18n import t
from flowpost.services.html_sanitize import visible_len
from flowpost.services.posts import TEXT_LIMIT, group_error, media_from_message, message_text, poll_from_message
from flowpost.services.publisher import Publisher
from flowpost.services.watermark import wm_configured, wm_settings

router = Router(name="create_post")

CONTENT = F.photo | F.video | F.animation | F.document | F.audio | F.text | F.poll


def initial_options(channel: Channel, is_ad: bool) -> dict:
    wm = wm_settings(channel.watermark)
    opts = {
        "signature": bool(channel.signature_on) and not is_ad,
        "watermark": bool(wm.get("enabled")) and wm_configured(channel.watermark),
    }
    if is_ad:
        opts.update({"ad_label": True, "auto_delete_hours": 24})
    return opts


def extract_source_signature(messages: list[Message], text: str) -> str:
    """The trailing line of `text` that names the forwarded channel — e.g. a self-promo
    link/title the source channel appends to its own posts. Returns the exact substring
    (with any blank separator lines before it) so it can be cut out verbatim later."""
    if not text:
        return ""
    origin = next((m.forward_origin for m in messages if m.forward_origin and m.forward_origin.type == "channel"), None)
    if origin is None:
        return ""
    chat = getattr(origin, "chat", None)
    username = getattr(chat, "username", None)
    needles = [n for n in (
        getattr(chat, "title", None),
        f"@{username}" if username else None,
        f"t.me/{username}" if username else None,
    ) if n]
    if not needles:
        return ""
    lines = text.split("\n")
    last = len(lines) - 1
    while last >= 0 and not lines[last].strip():
        last -= 1
    if last < 0 or not any(n.lower() in lines[last].lower() for n in needles):
        return ""
    start = last
    while start > 0 and not lines[start - 1].strip():
        start -= 1
    return "\n".join(lines[start:])


def extract_content(messages: list[Message]) -> tuple[str, list[dict], str]:
    media = [m for m in (media_from_message(x) for x in messages) if m]
    text = next((message_text(x) for x in messages if (x.text or x.caption)), "")
    return text, media, extract_source_signature(messages, text)


async def start_post(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    state: FSMContext,
    user: User,
    publisher: Publisher,
    *,
    is_ad: bool = False,
    text: str = "",
    media: list[dict] | None = None,
    source_signature: str = "",
    poll: dict | None = None,
) -> None:
    await state.clear()
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    if not channels:
        await message.answer(t("post.no_channels"), reply_markup=add_channel_inline_kb())
        return
    if len(channels) == 1:
        post = await posts_repo.create_post(
            session, channels[0].owner_id, [channels[0].id], is_ad=is_ad, options=initial_options(channels[0], is_ad),
            text=text, media=media, source_signature=source_signature, poll=poll,
        )
        note = t("post.ad_intro") if is_ad else None
        await open_editor(bot, message.chat.id, session, state, user, post, publisher, note=note)
        return
    post = await posts_repo.create_post(session, user.id, [], is_ad=is_ad, text=text, media=media,
                                         source_signature=source_signature, poll=poll)
    picker_text, picker_kb = await channel_picker(session, user, post.id)
    await message.answer(picker_text, reply_markup=picker_kb)


async def channel_picker(
    session: AsyncSession, user: User, post_id: int, folder_id: int = 0
) -> tuple[str, InlineKeyboardMarkup]:
    """The «which channel?» screen: folders plus loose channels at the root, a folder's channels inside it."""
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    if folder_id:
        folder = await folders_repo.get_folder(session, user.id, folder_id)
        if folder is None:
            return await channel_picker(session, user, post_id)
        inside_ids = set(await folders_repo.folder_channel_ids(session, folder_id))
        inside = [c for c in channels if c.id in inside_ids]
        text = t("fld.pick_title", icon=folder.icon, title=html.escape(folder.title)) + "\n\n"
        text += t("post.choose_channel") if inside else t("fld.empty_folder")
        return text, channels_pick_kb(inside, post_id, folder_id=folder_id)
    counts = await folders_repo.counts_by_folder(session, user.id)
    folders = [(f, counts[f.id]) for f in await folders_repo.list_folders(session, user.id) if counts.get(f.id)]
    grouped = await folders_repo.grouped_channel_ids(session, user.id)
    loose = [c for c in channels if c.id not in grouped]
    return t("post.choose_channel"), channels_pick_kb(loose, post_id, folders)


@router.callback_query(Fd.filter(F.a == "pick"))
async def cb_pick_folder(cb: CallbackQuery, callback_data: Fd, session: AsyncSession, user: User) -> None:
    post = await posts_repo.get_post(session, user.id, callback_data.p)
    if post is None:
        await cb.answer(t("err.post_not_found"), show_alert=True)
        return
    await cb.answer()
    text, kb = await channel_picker(session, user, post.id, callback_data.f)
    if cb.message:
        try:
            await cb.message.edit_text(text, reply_markup=kb)
        except TelegramBadRequest as e:
            if "not modified" not in str(e):
                await cb.message.answer(text, reply_markup=kb)


@router.callback_query(Nc.filter())
async def cb_pick_channel(
    cb: CallbackQuery,
    callback_data: Nc,
    bot: Bot,
    session: AsyncSession,
    state: FSMContext,
    user: User,
    publisher: Publisher,
) -> None:
    post = await posts_repo.get_post(session, user.id, callback_data.p)
    channel = await channels_repo.get_channel(session, user.id, callback_data.c)
    can_post = channel is not None and (
        channel.owner_id == user.id or await channel_admins_repo.has_permission(session, channel.id, user.id, "posts")
    )
    if post is None or channel is None or not can_post:
        await cb.answer(t("err.post_not_found"), show_alert=True)
        return
    await cb.answer()
    post.owner_id = channel.owner_id
    posts_repo.set_targets(post, [channel.id])
    post.options = {**initial_options(channel, post.is_ad), **(post.options or {})}
    await session.flush()
    if cb.message:
        await safe_delete(bot, cb.message.chat.id, [cb.message.message_id])
    note = t("post.ad_intro") if post.is_ad else None
    await open_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=note)


# The folder settings screen keeps its state while the user browses it: text there renames the folder
# (folders.router runs first), but anything else should still start a post instead of being swallowed.
@router.message(F.chat.type == "private", StateFilter(None, FolderInput.customize), CONTENT)
async def content_starts_post(
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
    if message.poll:
        await start_post(message, bot, session, state, user, publisher, poll=poll_from_message(message))
        return
    text, media, source_signature = extract_content(album or [message])
    error = group_error(media)
    if error:
        await message.answer(t(error))
        return
    if visible_len(text) > TEXT_LIMIT:
        await message.answer(t("err.text_too_long", max=TEXT_LIMIT))
        return
    await start_post(message, bot, session, state, user, publisher, text=text, media=media,
                      source_signature=source_signature)
