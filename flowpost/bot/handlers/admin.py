"""Admin commands for the bot owner: /stats, /chats, /expire, /broadcast."""
from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import date, datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import BaseFilter, Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Bc
from flowpost.bot.keyboards.common import btn, markup
from flowpost.bot.states import BroadcastInput
from flowpost.config import Settings
from flowpost.db.models import Broadcast, Channel, User
from flowpost.db.repo import stats as stats_repo
from flowpost.db.repo import users as users_repo
from flowpost.db.types import utcnow
from flowpost.services.billing.subscriptions import get_subscription
from flowpost.services.broadcast import AUDIENCES, audience_label
from flowpost.services.parsing import ParseError, parse_time
from flowpost.services.slots import fmt_hm, local_now, to_utc, tz_of
from flowpost.services.worker import Worker


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


# ---- /broadcast: a message to many users at once, now or later -----------------------------------

_WHEN_RE = re.compile(r"^\s*(?:(\d{1,2})\.(\d{1,2})(?:\.(\d{2}|\d{4}))?\s+)?(\d{1,2}\s*[:.]\s*\d{2})\s*$")


def parse_when(raw: str, tz_name: str, now: datetime) -> datetime | None:
    """"ГГ:ХХ" (today, or tomorrow once that time has passed), "ДД.ММ ГГ:ХХ" or "ДД.ММ.РРРР ГГ:ХХ" in the admin's
    time zone → UTC; None if it doesn't parse or is already in the past."""
    m = _WHEN_RE.match(raw or "")
    if not m:
        return None
    try:
        at = parse_time(m.group(4))
    except ParseError:
        return None
    today = now.astimezone(tz_of(tz_name)).date()
    if m.group(1) is None:
        run_at = to_utc(today, at, tz_name)
        if run_at <= now:
            run_at = to_utc(date.fromordinal(today.toordinal() + 1), at, tz_name)
        return run_at
    year = int(m.group(3)) if m.group(3) else today.year
    year += 2000 if year < 100 else 0
    try:
        day = date(year, int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    run_at = to_utc(day, at, tz_name)
    return run_at if run_at > now else None


def _when_text(send_at: datetime, tz_name: str) -> str:
    local = send_at.astimezone(tz_of(tz_name))
    return f"{local:%d.%m.%Y} о {fmt_hm(local)}"


async def _audience_kb(session: AsyncSession):
    counts = {a: len(await stats_repo.broadcast_recipients(session, a)) for a in AUDIENCES}
    return markup([
        *[[btn(f"{label} ({counts[a]})", Bc(a="aud", v=a))] for a, label in AUDIENCES.items()],
        [btn("✖️ Скасувати", Bc(a="cancel"))],
    ])


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    await state.set_state(BroadcastInput.message)
    await message.answer(
        "📣 <b>Розсилка</b>\n\nНадішліть повідомлення для розсилки: текст, фото, відео, файл — "
        "з форматуванням і емодзі. Воно піде від імені бота, без підпису «Переслано».\n\n"
        "Заплановані розсилки — /broadcasts.\n/cancel — скасувати."
    )


@router.message(StateFilter(BroadcastInput), Command("cancel"))
async def cancel_broadcast_input(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Розсилку скасовано.")


@router.message(StateFilter(BroadcastInput.message), F.media_group_id)
async def broadcast_album(message: Message) -> None:
    await message.answer("Альбом розіслати не вийде — надішліть одне повідомлення (одне фото чи відео з підписом).")


@router.message(StateFilter(BroadcastInput.message), ~F.text.startswith("/"))
async def broadcast_message(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    await bot.copy_message(message.chat.id, message.chat.id, message.message_id)
    await message.answer("👆 Так виглядатиме повідомлення. Кому надіслати?", reply_markup=await _audience_kb(session))


@router.callback_query(Bc.filter(F.a == "cancel"))
async def cancel_broadcast(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text("Розсилку скасовано.")
    await call.answer()


async def _draft(call: CallbackQuery, state: FSMContext) -> dict | None:
    """The message the admin is about to broadcast, or None (with an alert) once it's been sent or dropped."""
    data = await state.get_data()
    if "message_id" not in data:
        await state.clear()
        await call.answer("Повідомлення вже розіслане або скасоване — почніть знову з /broadcast.", show_alert=True)
        return None
    return data


@router.callback_query(Bc.filter(F.a == "aud"))
async def broadcast_audience(call: CallbackQuery, callback_data: Bc, state: FSMContext, session: AsyncSession) -> None:
    if await _draft(call, state) is None or callback_data.v not in AUDIENCES:
        return
    await state.set_state(BroadcastInput.message)
    count = len(await stats_repo.broadcast_recipients(session, callback_data.v))
    await call.answer()
    await call.message.edit_text(
        f"Кому: {audience_label(callback_data.v)} ({count})\n\nКоли надіслати?",
        reply_markup=markup([
            [btn("▶️ Надіслати зараз", Bc(a="now", v=callback_data.v))],
            [btn("🕒 Відкласти", Bc(a="later", v=callback_data.v))],
            [btn("↩️ Назад", Bc(a="back"))],
        ]),
    )


@router.callback_query(Bc.filter(F.a == "back"))
async def broadcast_back(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if await _draft(call, state) is None:
        return
    await state.set_state(BroadcastInput.message)
    await call.answer()
    await call.message.edit_text(
        "👆 Так виглядатиме повідомлення. Кому надіслати?", reply_markup=await _audience_kb(session)
    )


async def _create(
    session: AsyncSession, data: dict, audience: str, send_at: datetime, status_message_id: int | None
) -> Broadcast:
    bc = Broadcast(
        created_by=data["chat_id"], from_chat_id=data["chat_id"], message_id=data["message_id"],
        audience=audience, send_at=send_at, status_message_id=status_message_id,
    )
    session.add(bc)
    await session.commit()
    return bc


@router.callback_query(Bc.filter(F.a == "now"))
async def broadcast_now(
    call: CallbackQuery, callback_data: Bc, state: FSMContext, session: AsyncSession, worker: Worker
) -> None:
    data = await _draft(call, state)
    if data is None or callback_data.v not in AUDIENCES:
        return
    await state.clear()
    await call.answer()
    await call.message.edit_text(f"📣 Розсилку запущено…\n{audience_label(callback_data.v)}")
    await _create(session, data, callback_data.v, utcnow(), call.message.message_id)
    worker.wake()


@router.callback_query(Bc.filter(F.a == "later"))
async def broadcast_later(call: CallbackQuery, callback_data: Bc, state: FSMContext, user: User) -> None:
    if await _draft(call, state) is None or callback_data.v not in AUDIENCES:
        return
    await state.set_state(BroadcastInput.when)
    await state.update_data(audience=callback_data.v)
    await call.answer()
    now = local_now(user.tz)
    await call.message.edit_text(
        f"🕒 Коли надіслати? Напишіть час:\n\n"
        f"• <code>18:30</code> — сьогодні (або завтра, якщо цей час уже минув)\n"
        f"• <code>{now:%d.%m} 18:30</code> — конкретного дня\n\n"
        f"Часовий пояс: {html.escape(user.tz)}, зараз {fmt_hm(now)}.",
        reply_markup=markup([[btn("↩️ Назад", Bc(a="aud", v=callback_data.v))]]),
    )


@router.message(StateFilter(BroadcastInput.when), ~F.text.startswith("/"))
async def broadcast_when(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    data = await state.get_data()
    send_at = parse_when(message.text, user.tz, utcnow())
    if send_at is None:
        await message.answer(
            "Не вдалося розпізнати час або він уже минув. Приклади: <code>18:30</code>, <code>25.09 10:00</code>."
        )
        return
    await state.clear()
    await _create(session, data, data["audience"], send_at, None)
    count = len(await stats_repo.broadcast_recipients(session, data["audience"]))
    await message.answer(
        f"🕒 Розсилку заплановано на {_when_text(send_at, user.tz)}.\n"
        f"Кому: {audience_label(data['audience'])} (зараз {count})\n\n"
        "Не видаляйте це повідомлення з чату з ботом до відправки — бот копіює саме його.\n"
        "Список і скасування — /broadcasts."
    )


def _broadcasts_view(rows: list[Broadcast], tz_name: str):
    if not rows:
        return "Запланованих розсилок немає.", None
    lines, buttons = ["<b>📣 Розсилки в черзі</b>", ""], []
    for n, bc in enumerate(rows, 1):
        if bc.status == "sending":
            lines.append(f"{n}. ⏳ надсилається: {bc.sent + bc.blocked + bc.failed} / {bc.total} — "
                         f"{audience_label(bc.audience)}")
            buttons.append([btn(f"⏹ Зупинити №{n}", Bc(a="stop", v=str(bc.id)))])
        else:
            lines.append(f"{n}. 🕒 {_when_text(bc.send_at, tz_name)} — {audience_label(bc.audience)}")
            buttons.append([btn(f"✖️ Скасувати №{n}", Bc(a="stop", v=str(bc.id)))])
    return "\n".join(lines), markup(buttons)


async def _queued(session: AsyncSession) -> list[Broadcast]:
    return list((await session.scalars(
        select(Broadcast).where(Broadcast.status.in_(("pending", "sending"))).order_by(Broadcast.send_at)
    )).all())


@router.message(Command("broadcasts"))
async def cmd_broadcasts(message: Message, session: AsyncSession, user: User) -> None:
    text, kb = _broadcasts_view(await _queued(session), user.tz)
    await message.answer(text, reply_markup=kb)


@router.callback_query(Bc.filter(F.a == "stop"))
async def stop_broadcast(call: CallbackQuery, callback_data: Bc, session: AsyncSession, user: User) -> None:
    """Cancel a scheduled broadcast, or stop one that's being sent (it halts within a few dozen messages)."""
    bc = await session.get(Broadcast, int(callback_data.v)) if callback_data.v.isdigit() else None
    if bc is None or bc.status not in ("pending", "sending"):
        await call.answer("Ця розсилка вже завершилась.", show_alert=True)
    else:
        await call.answer("Розсилку зупинено." if bc.status == "sending" else "Розсилку скасовано.")
        bc.status = "cancelled"
        await session.commit()
    text, kb = _broadcasts_view(await _queued(session), user.tz)
    await call.message.edit_text(text, reply_markup=kb)


