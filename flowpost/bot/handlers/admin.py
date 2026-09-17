"""Admin commands for the bot owner: /stats, /expire."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.config import Settings
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
    await message.answer(
        "<b>📊 FlowPost</b>\n\n"
        f"👤 Users: {s['users_total']} (+{s['users_new_7d']} / 7d, active 7d: {s['active_7d']})\n"
        f"🧪 Active trials: {s['trials_active']}\n"
        f"💳 Active subscriptions: {s['subs_active']} ({providers})\n"
        f"📈 Conversion to paid: {s['conversion_pct']}%\n\n"
        f"📡 Active channels: {s['channels_active']}\n"
        f"🚀 Published: {s['published_24h']} / 24h, {s['published_7d']} / 7d\n"
        f"🕒 In queue: {s['scheduled']}\n"
        f"🤖 AI calls / 24h: {s['ai_calls_24h']}"
    )


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
