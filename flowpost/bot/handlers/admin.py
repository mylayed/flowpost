"""Admin commands for the bot owner: /stats, /chats, /expire, /broadcast."""
from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import BaseFilter, Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Bc
from flowpost.bot.keyboards.common import btn, markup
from flowpost.bot.states import BroadcastInput
from flowpost.config import Settings
from flowpost.db.models import Channel, User
from flowpost.db.repo import stats as stats_repo
from flowpost.db.repo import users as users_repo
from flowpost.db.types import utcnow
from flowpost.services.billing.subscriptions import get_subscription


log = logging.getLogger(__name__)


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, settings: Settings) -> bool:
        return bool(event.from_user and event.from_user.id in settings.admin_id_set)


router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.message(Command("stats"))
async def cmd_stats(message: Message, session: AsyncSession, settings: Settings) -> None:
    s = await stats_repo.admin_stats(session, utcnow(), settings)
    providers = ", ".join(f"{k}: {v}" for k, v in s["subs_by_provider"].items()) or "—"
    support = (
        f"\n\n🆘 Support: {s['support_users']} users (active 7d: {s['support_7d']}), "
        f"awaiting reply: {s['support_waiting']}"
    ) if settings.support_chat_id is not None else ""
    await message.answer(
        "<b>📊 FlowPost</b>\n\n"
        f"👤 Users: {s['users_total']} (+{s['users_new_7d']} / 7d, active 7d: {s['active_7d']})\n"
        f"🧪 Active trials: {s['trials_active']}\n"
        f"💳 Active subscriptions: {s['subs_active']} ({providers})\n"
        f"📈 Conversion to paid: {s['conversion_pct']}%\n\n"
        f"📡 Active channels: {s['channels_active']}\n"
        f"👥 Active groups: {s['groups_active']}\n"
        f"🚀 Published: {s['published_24h']} / 24h, {s['published_7d']} / 7d\n"
        f"🕒 In queue: {s['scheduled']}\n"
        f"🤖 AI calls / 24h: {s['ai_calls_24h']}"
        + support
    )


# Invite links the bot made for private channels, so /chats doesn't create a new one each time.
_invite_links: dict[int, str] = {}


async def _channel_url(bot: Bot, channel: Channel) -> str | None:
    """A link that opens the channel: its public address, or for a private one its primary invite link — or, when
    there's none, a separate link the bot creates (exporting a new primary one would revoke the owner's)."""
    if channel.username:
        return f"https://t.me/{channel.username}"
    if channel.chat_id in _invite_links:
        return _invite_links[channel.chat_id]
    try:
        url = getattr(await bot.get_chat(channel.chat_id), "invite_link", None)
        if not url:
            url = (await bot.create_chat_invite_link(channel.chat_id, name="FlowPost")).invite_link
    except TelegramAPIError as e:
        log.info("no invite link for %s: %s", channel.chat_id, e)
        return None
    _invite_links[channel.chat_id] = url
    return url


def _owner_link(owner: User) -> str:
    """Opens a private chat with the owner: by @username, or by id for those who have none."""
    if owner.username:
        return f'<a href="https://t.me/{owner.username}">@{owner.username}</a>'
    name = html.escape(owner.first_name or str(owner.tg_id))
    return f'<a href="tg://user?id={owner.tg_id}">{name}</a> (<code>{owner.tg_id}</code>)'


def _chat_line(n: int, channel: Channel, owner: User, url: str | None = None, *, private: bool = False) -> str:
    title = html.escape(channel.title or str(channel.chat_id))
    if url:
        title = f'<a href="{html.escape(url)}">{title}</a>'
    elif private:
        title += " (private)"
    return f"{n}. {title} — {_owner_link(owner)}"


def _pages(lines: list[str], limit: int = 4000) -> list[str]:
    """Split a long list into messages under Telegram's 4096-character limit."""
    pages, page = [], ""
    for line in lines:
        if page and len(page) + len(line) + 1 > limit:
            pages.append(page)
            page = ""
        page += ("\n" if page else "") + line
    return [*pages, page] if page else pages


@router.message(Command("chats"))
async def cmd_chats(message: Message, session: AsyncSession, bot: Bot) -> None:
    channels, groups = await stats_repo.active_chats(session)
    urls = await asyncio.gather(*(_channel_url(bot, c) for c, _ in channels))
    lines = [f"<b>📡 Channels ({len(channels)})</b>"]
    lines += [
        _chat_line(i, c, o, url, private=True) for i, ((c, o), url) in enumerate(zip(channels, urls), 1)
    ] or ["—"]
    lines += ["", f"<b>👥 Groups ({len(groups)})</b>"]
    lines += [_chat_line(i, c, o) for i, (c, o) in enumerate(groups, 1)] or ["—"]
    for page in _pages(lines):
        await message.answer(page, disable_web_page_preview=True)


def _args(command: CommandObject, count: int) -> list[str] | None:
    parts = (command.args or "").split()
    return parts if len(parts) == count else None


@router.message(Command("expire"))
async def cmd_expire(message: Message, command: CommandObject, session: AsyncSession) -> None:
    args = _args(command, 1)
    if not args or not args[0].isdigit():
        await message.answer("Usage: /expire tg_id")
        return
    user = await users_repo.get_by_tg(session, int(args[0]))
    if user is None:
        await message.answer("User not found.")
        return
    now = utcnow()
    user.trial_ends_at = now
    sub = await get_subscription(session, user.id)
    if sub is not None:
        sub.current_period_end = now
        sub.status = "expired"
    await message.answer(f"⛔ Access of {args[0]} expired (trial and subscription).")


# Telegram lets a bot send about 30 messages a second to different users; stay a little below that.
BROADCAST_DELAY = 0.05
PROGRESS_EVERY = 100
AUDIENCES = {
    "owners": "👑 Лише власникам каналів",
    "channels": "👥 Власникам і адмінам каналів",
    "nochannels": "🆕 Тим, хто ще не підключив канал",
    "all": "👤 Усім користувачам",
}


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    await state.set_state(BroadcastInput.message)
    await message.answer(
        "📣 <b>Розсилка</b>\n\nНадішліть повідомлення, яке отримають адміни: текст, фото, відео, файл — "
        "з форматуванням і емодзі. Воно піде від імені бота, без підпису «Переслано».\n\n/cancel — скасувати."
    )


@router.message(StateFilter(BroadcastInput.message), Command("cancel"))
async def cancel_broadcast_input(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Розсилку скасовано.")


@router.message(StateFilter(BroadcastInput.message), F.media_group_id)
async def broadcast_album(message: Message) -> None:
    await message.answer("Альбом розіслати не вийде — надішліть одне повідомлення (одне фото чи відео з підписом).")


@router.message(StateFilter(BroadcastInput.message), ~F.text.startswith("/"))
async def broadcast_message(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    counts = {a: len(await stats_repo.broadcast_recipients(session, a)) for a in AUDIENCES}
    await bot.copy_message(message.chat.id, message.chat.id, message.message_id)
    await message.answer(
        "👆 Так виглядатиме повідомлення. Кому надіслати?",
        reply_markup=markup([
            *[[btn(f"{label} ({counts[a]})", Bc(a="send", v=a))] for a, label in AUDIENCES.items()],
            [btn("✖️ Скасувати", Bc(a="cancel"))],
        ]),
    )


@router.callback_query(Bc.filter(F.a == "cancel"))
async def cancel_broadcast(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text("Розсилку скасовано.")
    await call.answer()


@router.callback_query(Bc.filter(F.a == "send"))
async def send_broadcast(
    call: CallbackQuery, callback_data: Bc, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    data = await state.get_data()
    await state.clear()
    if "message_id" not in data or callback_data.v not in AUDIENCES:
        await call.answer("Повідомлення вже розіслане або скасоване — почніть знову з /broadcast.", show_alert=True)
        return
    await call.answer()
    recipients = await stats_repo.broadcast_recipients(session, callback_data.v)
    await call.message.edit_text(f"📣 Розсилка: 0 / {len(recipients)}…")
    sent, blocked, failed = await _deliver(bot, data["chat_id"], data["message_id"], recipients, call.message)
    if blocked:
        await session.execute(update(User).where(User.id.in_(blocked)).values(is_blocked=True))
    await call.message.edit_text(
        f"✅ <b>Розсилку завершено</b>\n\n"
        f"Доставлено: {sent} / {len(recipients)}\n"
        f"Заблокували бота: {len(blocked)}\n"
        f"Помилки: {failed}"
    )


async def _deliver(
    bot: Bot, chat_id: int, message_id: int, recipients: list[tuple[int, int]], status: Message
) -> tuple[int, list[int], int]:
    """Copy the message to each recipient; returns (delivered, ids of users who blocked the bot, other failures)."""
    sent, blocked, failed = 0, [], 0
    for n, (user_id, tg_id) in enumerate(recipients, 1):
        for attempt in range(2):
            try:
                await bot.copy_message(tg_id, chat_id, message_id)
                sent += 1
            except TelegramRetryAfter as e:
                if attempt == 0:
                    await asyncio.sleep(e.retry_after)
                    continue
                failed += 1
            except TelegramForbiddenError:
                blocked.append(user_id)
            except TelegramAPIError as e:
                log.warning("broadcast to %s failed: %s", tg_id, e)
                failed += 1
            break
        if n % PROGRESS_EVERY == 0 and n < len(recipients):
            try:
                await bot.edit_message_text(
                    chat_id=status.chat.id, message_id=status.message_id, text=f"📣 Розсилка: {n} / {len(recipients)}…"
                )
            except TelegramAPIError:
                pass
        await asyncio.sleep(BROADCAST_DELAY)
    return sent, blocked, failed
