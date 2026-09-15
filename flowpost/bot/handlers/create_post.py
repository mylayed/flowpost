"""Starting a new post: via the menu button or by simply sending content to the bot."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Nc
from flowpost.bot.handlers.editor.view import open_editor, safe_delete
from flowpost.bot.keyboards.common import add_channel_inline_kb
from flowpost.bot.keyboards.editor import channels_pick_kb
from flowpost.db.models import Channel, User
from flowpost.db.repo import channel_admins as channel_admins_repo
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.i18n import t
from flowpost.services.html_sanitize import visible_len
from flowpost.services.posts import TEXT_LIMIT, group_error, media_from_message, message_text
from flowpost.services.publisher import Publisher
from flowpost.services.watermark import wm_configured, wm_settings

router = Router(name="create_post")

CONTENT = F.photo | F.video | F.animation | F.document | F.audio | F.text


def initial_options(channel: Channel, is_ad: bool) -> dict:
    wm = wm_settings(channel.watermark)
    opts = {
        "signature": bool(channel.signature_on) and not is_ad,
        "watermark": bool(wm.get("enabled")) and wm_configured(channel.watermark),
    }
    if is_ad:
        opts.update({"ad_label": True, "auto_delete_hours": 24})
    return opts


def extract_source_signature(messages: list[Message]) -> str:
    """The author signature Telegram attaches when forwarding a signed channel post."""
    for m in messages:
        origin = m.forward_origin
        if origin is not None and origin.type == "channel":
            signature = getattr(origin, "author_signature", None)
            if signature:
                return signature
    return ""


def extract_content(messages: list[Message]) -> tuple[str, list[dict], str]:
    media = [m for m in (media_from_message(x) for x in messages) if m]
    text = next((message_text(x) for x in messages if (x.text or x.caption)), "")
    return text, media, extract_source_signature(messages)


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
) -> None:
    await state.clear()
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    if not channels:
        await message.answer(t("post.no_channels"), reply_markup=add_channel_inline_kb())
        return
    if len(channels) == 1:
        post = await posts_repo.create_post(
            session, channels[0].owner_id, [channels[0].id], is_ad=is_ad, options=initial_options(channels[0], is_ad),
            text=text, media=media, source_signature=source_signature,
        )
        note = t("post.ad_intro") if is_ad else None
        await open_editor(bot, message.chat.id, session, state, user, post, publisher, note=note)
        return
    post = await posts_repo.create_post(session, user.id, [], is_ad=is_ad, text=text, media=media,
                                         source_signature=source_signature)
    await message.answer(t("post.choose_channel"), reply_markup=channels_pick_kb(channels, post.id))


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


@router.message(F.chat.type == "private", StateFilter(None), CONTENT)
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
