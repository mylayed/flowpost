"""Subscription: open the billing Mini App, cancel a legacy LiqPay auto-renewal, /paysupport, /terms."""
from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Bl
from flowpost.bot.keyboards.common import btn, markup, pay_btn
from flowpost.config import Settings
from flowpost.db.models import User
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services.billing.liqpay import LiqPayClient
from flowpost.services.billing.subscriptions import get_subscription
from flowpost.services.slots import fmt_date, tz_of

log = logging.getLogger(__name__)
router = Router(name="billing")


def liqpay_client(settings: Settings) -> LiqPayClient | None:
    if not (settings.liqpay_enabled and settings.liqpay_public_key and settings.liqpay_private_key.get_secret_value()):
        return None
    return LiqPayClient(settings.liqpay_public_key, settings.liqpay_private_key.get_secret_value(), settings.liqpay_sandbox)


async def billing_view(session: AsyncSession, user: User, settings: Settings) -> tuple[str, InlineKeyboardMarkup | None]:
    rows = []
    if settings.webapp_url:
        text = t("pay.open")
        rows.append([pay_btn(settings)])
    else:
        text = t("pay.unavailable", contact=html.escape(settings.support_contact or "—"))
    sub = await get_subscription(session, user.id)
    # Customers still on the old monthly LiqPay subscription must be able to stop its auto-renewal.
    if sub and sub.provider == "liqpay" and sub.status == "active" and sub.current_period_end > utcnow():
        rows.append([btn(t("pay.cancel_btn"), Bl(a="cancel"))])
    return text, markup(rows) if rows else None


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, session: AsyncSession, user: User, settings: Settings) -> None:
    text, kb = await billing_view(session, user, settings)
    await message.answer(text, reply_markup=kb)


@router.callback_query(Bl.filter(F.a == "open"))
async def bl_open(cb: CallbackQuery, bot: Bot, session: AsyncSession, user: User, settings: Settings) -> None:
    await cb.answer()
    text, kb = await billing_view(session, user, settings)
    await bot.send_message(cb.from_user.id, text, reply_markup=kb)


@router.callback_query(Bl.filter(F.a.in_({"cancel", "cancelok"})))
async def bl_cancel(cb: CallbackQuery, callback_data: Bl, session: AsyncSession, user: User, settings: Settings) -> None:
    sub = await get_subscription(session, user.id)
    if sub is None or sub.provider != "liqpay":
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    if callback_data.a == "cancel":
        await cb.answer()
        kb = markup([[btn(t("pay.cancel_yes"), Bl(a="cancelok"))], [btn(t("btn.back"), Bl(a="open"))]])
        if cb.message:
            await cb.message.edit_text(t("pay.cancel_confirm"), reply_markup=kb)
        return
    try:
        if sub.provider_sub_id:
            client = liqpay_client(settings)
            if client is not None:
                await client.unsubscribe(sub.provider_sub_id)
    except Exception as e:  # noqa: BLE001 - payment providers may fail in many ways
        log.warning("subscription change failed: %s", e)
        await cb.answer(t("pay.change_failed"), show_alert=True)
        return
    sub.status = "cancelled"
    await session.flush()
    await cb.answer()
    local = sub.current_period_end.astimezone(tz_of(user.tz))
    if cb.message:
        await cb.message.edit_text(t("pay.cancelled", date=fmt_date(local.date(), user.lang)))


@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message, settings: Settings) -> None:
    await message.answer(t("pay.support", contact=html.escape(settings.support_contact or "—")))


@router.message(Command("terms"))
async def cmd_terms(message: Message, settings: Settings) -> None:
    await message.answer(
        t("pay.terms", days=settings.trial_days, posts=settings.trial_posts, free=settings.free_posts_per_day)
    )
