"""«Налаштування»: language, time zone, subscription, support."""
from __future__ import annotations

import html
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Bl, St
from flowpost.bot.keyboards.common import btn, chunked, markup, pay_btn
from flowpost.bot.keyboards.main_menu import main_menu_kb
from flowpost.bot.states import SettingsInput
from flowpost.config import Settings
from flowpost.db.models import User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.types import utcnow
from flowpost.i18n import LANG_TITLES, set_locale, t
from flowpost.services.billing.subscriptions import Access, get_access
from flowpost.services.slots import fmt_date, fmt_hm, local_now, tz_of

router = Router(name="settings")

TIMEZONES = ["Europe/Kyiv", "Europe/Warsaw", "Europe/Berlin", "Europe/London", "UTC", "America/New_York"]


def access_line(access: Access, user: User) -> str:
    if access.kind == "paid" and access.until:
        local = access.until.astimezone(tz_of(user.tz))
        days_left = max(0, (access.until - utcnow()).days)
        key = "set.sub_cancelled" if access.sub and access.sub.status == "cancelled" else "set.sub_paid"
        return t(
            key, date=fmt_date(local.date(), user.lang), days=days_left,
            provider=t("provider." + (access.sub.provider if access.sub else "manual")),
        )
    if access.kind == "trial" and access.until:
        local = access.until.astimezone(tz_of(user.tz))
        days_left = max(0, (access.until - utcnow()).days)
        return t("set.sub_trial", date=fmt_date(local.date(), user.lang), time=fmt_hm(local), days=days_left)
    return t("set.sub_none")


def _liqpay_renewing(access: Access) -> bool:
    sub = access.sub
    return access.kind == "paid" and sub is not None and sub.provider == "liqpay" and sub.status == "active"


async def settings_view(session: AsyncSession, user: User, settings: Settings) -> tuple[str, InlineKeyboardMarkup]:
    access = await get_access(session, user)
    lines = [
        t("set.title"),
        "",
        t("set.lang", lang=LANG_TITLES.get(user.lang, user.lang)),
        t("set.tz", tz=html.escape(user.tz), time=fmt_hm(local_now(user.tz))),
        access_line(access, user),
    ]
    kb = markup([
        [btn(t("set.change_lang"), St(a="lang"))],
        [btn(t("set.change_tz"), St(a="tz"))],
        [btn(t("set.interface"), St(a="ui"))],
        [pay_btn(settings, t("set.manage_sub") if access.kind == "paid" else t("btn.pay"))],
        [btn(t("pay.cancel_btn"), Bl(a="cancel"))] if _liqpay_renewing(access) else [],
        [btn(t("set.support"), St(a="support"))],
    ])
    return "\n".join(lines), kb


async def send_settings(message: Message, session: AsyncSession, user: User, settings: Settings) -> None:
    text, kb = await settings_view(session, user, settings)
    await message.answer(text, reply_markup=kb)


async def _edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None) -> None:
    if cb.message is None:
        return
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await cb.message.answer(text, reply_markup=kb)


@router.callback_query(St.filter(F.a == "back"))
async def st_back(cb: CallbackQuery, session: AsyncSession, state: FSMContext, user: User, settings: Settings) -> None:
    await state.clear()
    await cb.answer()
    await _edit(cb, *await settings_view(session, user, settings))


@router.callback_query(St.filter(F.a == "lang"))
async def st_lang(cb: CallbackQuery, bot: Bot, session: AsyncSession, user: User, settings: Settings) -> None:
    user.lang = "en" if user.lang == "uk" else "uk"
    set_locale(user.lang)
    await session.flush()
    await cb.answer()
    await _edit(cb, *await settings_view(session, user, settings))
    await bot.send_message(cb.from_user.id, t("set.lang_changed"), reply_markup=main_menu_kb())


@router.callback_query(St.filter(F.a == "ui"))
async def st_interface(cb: CallbackQuery) -> None:
    await cb.answer()
    await _edit(cb, t("set.interface_title") + "\n\n" + t("set.interface_text"), markup([
        [btn(t("set.interface_folders"), St(a="ui_folders"))],
        [btn(t("set.interface_channels"), St(a="ui_channels"))],
        [btn(t("btn.back"), St(a="back"))],
    ]))


PER_PAGE_CHOICES = [4, 6, 8, 10, 20, 30, 40, 50]


def channels_ui_view(user: User) -> tuple[str, InlineKeyboardMarkup]:
    return t("set.ch_title") + "\n\n" + t("set.ch_text"), markup([
        [btn(t("set.ch_order"), St(a="ui_order"))],
        [btn(t("set.ch_per_page", n=user.channels_per_page), St(a="ui_pp"))],
        [btn(t("btn.back"), St(a="ui"))],
    ])


async def channel_order_view(session: AsyncSession, user: User) -> tuple[str, InlineKeyboardMarkup]:
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    order = list(user.channel_order or [])
    rows = chunked([
        btn(
            (f"{order.index(c.id) + 1}. " if c.id in order else "")
            + ("📢 " if c.kind == "channel" else "👥 ") + c.title,
            St(a="ui_ord", v=str(c.id)),
        )
        for c in channels
    ], 2)
    rows.append([btn(t("btn.back"), St(a="ui_channels"))])
    text = t("set.ch_order_title") + "\n\n" + (t("set.ch_order_text") if channels else t("set.ch_order_empty"))
    return text, markup(rows)


@router.callback_query(St.filter(F.a == "ui_channels"))
async def st_channels_ui(cb: CallbackQuery, user: User) -> None:
    await cb.answer()
    await _edit(cb, *channels_ui_view(user))


@router.callback_query(St.filter(F.a == "ui_pp"))
async def st_per_page(cb: CallbackQuery, user: User) -> None:
    await cb.answer()
    rows = chunked([
        btn(("✅ " if n == user.channels_per_page else "◯ ") + str(n), St(a="ui_ppset", v=str(n)))
        for n in PER_PAGE_CHOICES
    ], 4)
    rows.append([btn(t("btn.back"), St(a="ui_channels"))])
    await _edit(cb, t("set.ch_per_page_title") + "\n\n" + t("set.ch_per_page_text"), markup(rows))


@router.callback_query(St.filter(F.a == "ui_ppset"))
async def st_per_page_set(
    cb: CallbackQuery, callback_data: St, session: AsyncSession, user: User
) -> None:
    if not callback_data.v.isdigit() or int(callback_data.v) not in PER_PAGE_CHOICES:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    user.channels_per_page = int(callback_data.v)
    await session.flush()
    await cb.answer(t("set.saved"))
    await _edit(cb, *channels_ui_view(user))


@router.callback_query(St.filter(F.a == "ui_order"))
async def st_channel_order(cb: CallbackQuery, session: AsyncSession, user: User) -> None:
    await cb.answer()
    await _edit(cb, *await channel_order_view(session, user))


@router.callback_query(St.filter(F.a == "ui_ord"))
async def st_channel_order_toggle(
    cb: CallbackQuery, callback_data: St, session: AsyncSession, user: User
) -> None:
    channel = await channels_repo.get_channel(session, user.id, int(callback_data.v or 0))
    if channel is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    order = [c for c in (user.channel_order or []) if c != channel.id]
    if len(order) == len(user.channel_order or []):
        order.append(channel.id)
    user.channel_order = order
    await session.flush()
    await cb.answer()
    await _edit(cb, *await channel_order_view(session, user))


@router.callback_query(St.filter(F.a == "tz"))
async def st_tz(cb: CallbackQuery, user: User) -> None:
    await cb.answer()
    rows = [[btn(("✅ " if tz == user.tz else "") + tz, St(a="tzset", v=tz))] for tz in TIMEZONES]
    rows.append([btn(t("set.tz_manual"), St(a="tzman"))])
    rows.append([btn(t("btn.back"), St(a="back"))])
    await _edit(cb, t("set.tz_title", tz=html.escape(user.tz)), markup(rows))


def _valid_tz(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except Exception:  # noqa: BLE001
        return False


@router.callback_query(St.filter(F.a == "tzset"))
async def st_tz_set(
    cb: CallbackQuery, callback_data: St, session: AsyncSession, user: User, settings: Settings
) -> None:
    if not _valid_tz(callback_data.v):
        await cb.answer(t("set.tz_invalid"), show_alert=True)
        return
    user.tz = callback_data.v
    await session.flush()
    await cb.answer(t("set.saved"))
    await _edit(cb, *await settings_view(session, user, settings))


@router.callback_query(St.filter(F.a == "tzman"))
async def st_tz_manual(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(SettingsInput.tz)
    await _edit(cb, t("set.tz_prompt"), markup([[btn(t("btn.back"), St(a="back"))]]))


@router.message(SettingsInput.tz, F.text)
async def in_tz(message: Message, session: AsyncSession, state: FSMContext, user: User, settings: Settings) -> None:
    name = (message.text or "").strip()
    if not _valid_tz(name):
        await message.answer(t("set.tz_invalid"))
        return
    user.tz = name
    await session.flush()
    await state.clear()
    text, kb = await settings_view(session, user, settings)
    await message.answer(t("set.saved") + "\n\n" + text, reply_markup=kb)


@router.callback_query(St.filter(F.a == "support"))
async def st_support(cb: CallbackQuery, settings: Settings) -> None:
    await cb.answer()
    if cb.message:
        await cb.message.answer(t("set.support_text", contact=html.escape(settings.support_contact or "—")))
