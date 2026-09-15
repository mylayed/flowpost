"""«Редагувати пост»: pick a recent published/scheduled post or forward it from the channel."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ep
from flowpost.bot.handlers.editor.view import open_editor
from flowpost.bot.keyboards.common import btn, markup
from flowpost.bot.states import EditPublished
from flowpost.db.models import Channel, Post, User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.db.repo import publications as pubs_repo
from flowpost.i18n import t
from flowpost.services.html_sanitize import snippet
from flowpost.services.posts import part_icon
from flowpost.services.publisher import Publisher

router = Router(name="edit_post")
STATUS_ICONS = {"published": "✅", "scheduled": "🕒"}


async def _channel_picker(channels: list[Channel]) -> tuple[str, InlineKeyboardMarkup]:
    rows = [[btn(("📢 " if c.kind == "channel" else "👥 ") + c.title, Ep(a="pick", c=c.id))] for c in channels]
    rows.append([btn(t("plan.all_channels"), Ep(a="pick", c=0))])
    return t("editp.pick_channel"), markup(rows)


async def _post_list_view(session: AsyncSession, user: User, channel_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    channel_ids = [channel_id] if channel_id else None
    posts = await posts_repo.recent_posts(session, user.id, ("published", "scheduled"), limit=10, channel_ids=channel_ids)
    rows = []
    for post in posts:
        first = post.parts[0] if post.parts else None
        label = f"{STATUS_ICONS.get(post.status, '•')} {part_icon(first) if first else ''} "
        label += snippet(first.text_html, 34) if first and first.text_html else t("parts.no_text")
        rows.append([btn(label, Ep(a="open", id=post.id))])
    text = t("editp.title") + "\n\n" + (t("editp.help") if posts else t("editp.empty"))
    return text, markup(rows) if rows else None


async def send_list(message: Message, session: AsyncSession, state: FSMContext, user: User) -> None:
    await state.clear()
    await state.set_state(EditPublished.waiting_forward)
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    if len(channels) > 1:
        text, kb = await _channel_picker(channels)
        await message.answer(text, reply_markup=kb)
        return
    channel_id = channels[0].id if channels else 0
    text, kb = await _post_list_view(session, user, channel_id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(Ep.filter(F.a == "pick"))
async def ep_pick(cb: CallbackQuery, callback_data: Ep, session: AsyncSession, user: User) -> None:
    await cb.answer()
    text, kb = await _post_list_view(session, user, callback_data.c)
    if cb.message is None:
        return
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await cb.message.answer(text, reply_markup=kb)


async def _open(bot: Bot, chat_id: int, session: AsyncSession, state: FSMContext, user: User, post: Post, publisher: Publisher) -> None:
    note = t("editp.published_note") if post.status == "published" else None
    await open_editor(bot, chat_id, session, state, user, post, publisher, note=note)


@router.callback_query(Ep.filter(F.a == "open"))
async def ep_open(
    cb: CallbackQuery, callback_data: Ep, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post = await posts_repo.get_post(session, user.id, callback_data.id)
    if post is None:
        await cb.answer(t("err.post_not_found"), show_alert=True)
        return
    await cb.answer()
    await _open(bot, cb.from_user.id, session, state, user, post, publisher)


@router.message(EditPublished.waiting_forward, F.forward_origin)
async def ep_forwarded(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher
) -> None:
    origin = message.forward_origin
    chat = getattr(origin, "chat", None)
    message_id = getattr(origin, "message_id", None)
    if chat is None or message_id is None:
        await message.answer(t("editp.forward_channel_only"))
        return
    channels = [c for c in await channels_repo.list_channels(session, user.id, active_only=False) if c.chat_id == chat.id]
    if not channels:
        await message.answer(t("editp.not_connected"))
        return
    pub = await pubs_repo.find_by_channel_message(session, user.id, [c.id for c in channels], message_id)
    post = await posts_repo.get_post(session, user.id, pub.post_id) if pub else None
    if post is None:
        await message.answer(t("editp.not_found"))
        return
    await _open(bot, message.chat.id, session, state, user, post, publisher)


@router.message(EditPublished.waiting_forward)
async def ep_wrong(message: Message) -> None:
    await message.answer(t("editp.help"))
