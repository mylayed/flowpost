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
from flowpost.bot.keyboards.common import btn, markup, pay_btn
from flowpost.bot.keyboards.main_menu import main_menu_kb
from flowpost.bot.states import SettingsInput
from flowpost.config import Settings
from flowpost.db.models import User
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
