"""Admin commands for the bot owner: /stats, /chats, /expire."""
from __future__ import annotations

import html

from aiogram import Router
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.config import Settings
from flowpost.db.models import Channel, User
from flowpost.db.repo import stats as stats_repo
from flowpost.db.repo import users as users_repo
from flowpost.db.types import utcnow
from flowpost.services.billing.subscriptions import get_subscription


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message, settings: Settings) -> bool:
        return bool(message.from_user and message.from_user.id in settings.admin_id_set)


router = Router(name="admin")
router.message.filter(IsAdmin())


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


def _chat_line(n: int, channel: Channel, owner: User, *, link: bool) -> str:
    title = html.escape(channel.title or str(channel.chat_id))
    if link and channel.username:
        title = f'<a href="https://t.me/{channel.username}">{title}</a>'
    elif link:
        title += " (private)"
    who = f"@{owner.username}" if owner.username else f"<code>{owner.tg_id}</code>"
    return f"{n}. {title} — {who}"


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
async def cmd_chats(message: Message, session: AsyncSession) -> None:
    channels, groups = await stats_repo.active_chats(session)
    lines = [f"<b>📡 Channels ({len(channels)})</b>"]
    lines += [_chat_line(i, c, o, link=True) for i, (c, o) in enumerate(channels, 1)] or ["—"]
    lines += ["", f"<b>👥 Groups ({len(groups)})</b>"]
    lines += [_chat_line(i, c, o, link=False) for i, (c, o) in enumerate(groups, 1)] or ["—"]
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
