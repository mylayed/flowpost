"""The owner's /broadcast: one message copied to many users at Telegram's pace, now or at a set time. Progress is
saved as it goes, so a broadcast cut off by a restart continues from the next recipient."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from flowpost.bot.callbacks import Pj
from flowpost.bot.keyboards.common import pay_btn
from flowpost.config import Settings
from flowpost.db.models import Broadcast, User
from flowpost.db.repo import stats as stats_repo
from flowpost.db.types import utcnow
from flowpost.i18n import t

log = logging.getLogger(__name__)

# Telegram lets a bot send about 30 messages a second to different users; stay a little below that.
BROADCAST_DELAY = 0.05
SAVE_EVERY = 25       # progress (and a cancel from /broadcasts) is picked up this often
PROGRESS_EVERY = 100  # the admin's progress message is updated this often

AUDIENCES = {
    "owners": "👑 Лише власникам каналів",
    "channels": "👥 Власникам і адмінам каналів",
    "nochannels": "🆕 Тим, хто ще не підключив канал",
    "all": "👤 Усім користувачам",
}


def build_markup(buttons: list, settings: Settings, lang: str | None = None) -> InlineKeyboardMarkup | None:
    """The broadcast's buttons for one recipient: link rows as they are, and the templates in their language —
    «Підключити канал» opens the same add-channel screen as the menu, «Керувати підпискою» the billing Mini App."""
    rows = []
    for row in buttons or []:
        if isinstance(row, dict) and row.get("add_channel"):
            text = t("btn.add_channel", locale=lang)
            rows.append([InlineKeyboardButton(text=text, callback_data=Pj(a="add").pack())])
        elif isinstance(row, dict) and row.get("manage_sub"):
            rows.append([pay_btn(settings, t("btn.manage_sub", locale=lang))])
        elif isinstance(row, list):
            rows.append([InlineKeyboardButton(text=b["text"], url=b["url"]) for b in row])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def audience_label(audience: str) -> str:
    return AUDIENCES.get(audience, audience)


def summary_text(bc: Broadcast) -> str:
    head = "⏹ <b>Розсилку зупинено</b>" if bc.status == "cancelled" else "✅ <b>Розсилку завершено</b>"
    return (
        f"{head}\n{audience_label(bc.audience)}\n\n"
        f"Доставлено: {bc.sent} / {bc.total}\n"
        f"Заблокували бота: {bc.blocked}\n"
        f"Помилки: {bc.failed}"
    )


def _progress_text(bc: Broadcast, done: int) -> str:
    return f"📣 Розсилка: {done} / {bc.total}…\n{audience_label(bc.audience)}"


async def _copy(bot: Bot, settings: Settings, bc: Broadcast, tg_id: int, lang: str) -> str:
    """"sent", "blocked" or "failed"."""
    for attempt in range(2):
        try:
            await bot.copy_message(
                tg_id, bc.from_chat_id, bc.message_id, reply_markup=build_markup(bc.buttons, settings, lang)
            )
            return "sent"
        except TelegramRetryAfter as e:
            if attempt == 0:
                await asyncio.sleep(e.retry_after)
                continue
        except TelegramForbiddenError:
            return "blocked"
        except TelegramAPIError as e:
            log.warning("broadcast %s to %s failed: %s", bc.id, tg_id, e)
            return "failed"
    return "failed"


async def _status_message(bot: Bot, bc: Broadcast, text: str) -> None:
    """Show `text` in the admin's progress message, or send it anew when there's none to edit."""
    try:
        if bc.status_message_id is not None:
            await bot.edit_message_text(chat_id=bc.created_by, message_id=bc.status_message_id, text=text)
        else:
            bc.status_message_id = (await bot.send_message(bc.created_by, text)).message_id
    except TelegramAPIError as e:
        if "not modified" not in str(e) and bc.status_message_id is not None:
            try:
                bc.status_message_id = (await bot.send_message(bc.created_by, text)).message_id
            except TelegramAPIError:
                pass


async def run(bot: Bot, sessionmaker: async_sessionmaker, settings: Settings, broadcast_id: int) -> None:
    """Send a broadcast the worker has marked "sending", from where it left off."""
    async with sessionmaker() as session:
        bc = await session.get(Broadcast, broadcast_id)
        if bc is None or bc.status != "sending":
            return
        recipients = await stats_repo.broadcast_recipients(session, bc.audience, after_user_id=bc.last_user_id)
        if bc.last_user_id == 0:
            bc.total = len(recipients)
        await _status_message(bot, bc, _progress_text(bc, bc.sent + bc.blocked + bc.failed))
        await session.commit()

        blocked: list[int] = []
        for n, (user_id, tg_id, lang) in enumerate(recipients, 1):
            outcome = await _copy(bot, settings, bc, tg_id, lang)
            if outcome == "sent":
                bc.sent += 1
            elif outcome == "blocked":
                bc.blocked += 1
                blocked.append(user_id)
            else:
                bc.failed += 1
            bc.last_user_id = user_id
            if n % SAVE_EVERY == 0 or n == len(recipients):
                if blocked:
                    await session.execute(update(User).where(User.id.in_(blocked)).values(is_blocked=True))
                    blocked.clear()
                stopped = await session.scalar(select(Broadcast.status).where(Broadcast.id == bc.id)) == "cancelled"
                if stopped:
                    bc.status = "cancelled"
                await session.commit()
                if stopped:
                    break
            if n % PROGRESS_EVERY == 0 and n < len(recipients):
                await _status_message(bot, bc, _progress_text(bc, bc.sent + bc.blocked + bc.failed))
            await asyncio.sleep(BROADCAST_DELAY)

        if bc.status == "sending":
            bc.status = "done"
        bc.finished_at = utcnow()
        await _status_message(bot, bc, summary_text(bc))
        await session.commit()
