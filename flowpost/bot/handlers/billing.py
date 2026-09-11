"""Subscription: Telegram Stars + LiqPay card checkout, /paysupport, /terms."""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Bl, St
from flowpost.bot.handlers.settings import access_line
from flowpost.bot.keyboards.common import btn, markup, url_btn
from flowpost.config import Settings
from flowpost.db.models import User
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services import analytics
from flowpost.services.billing.liqpay import LiqPayClient
from flowpost.services.billing.stars import create_subscription_link, parse_payload
from flowpost.services.billing.subscriptions import extend_subscription, get_access, get_subscription, record_payment
from flowpost.services.slots import fmt_date, tz_of

log = logging.getLogger(__name__)
router = Router(name="billing")


def liqpay_client(settings: Settings) -> LiqPayClient | None:
    if not (settings.liqpay_enabled and settings.liqpay_public_key and settings.liqpay_private_key.get_secret_value()):
        return None
    return LiqPayClient(settings.liqpay_public_key, settings.liqpay_private_key.get_secret_value(), settings.liqpay_sandbox)


async def billing_view(bot: Bot, session: AsyncSession, user: User, settings: Settings) -> tuple[str, InlineKeyboardMarkup]:
    access = await get_access(session, user)
    lines = [
        t("pay.title"),
        "",
        t("pay.features"),
        "",
        t("pay.price", usd=f"{settings.sub_price_usd:g}", stars=settings.stars_price),
        access_line(access, user),
    ]
    rows = []
    if settings.stars_enabled:
        try:
            link = await create_subscription_link(bot, user.id, settings, user.lang)
            rows.append([url_btn(t("pay.stars_btn", stars=settings.stars_price), link)])
        except TelegramAPIError as e:
            log.warning("create_invoice_link failed: %s", e)
    client = liqpay_client(settings)
    if client is not None:
        me = await bot.me()
        url = client.checkout_url(
            user_id=user.id,
            amount=settings.liqpay_amount,
            currency=settings.liqpay_currency,
            description=t("pay.liqpay_desc", locale=user.lang),
            language=user.lang,
            server_url=settings.liqpay_callback_url,
            result_url=f"https://t.me/{me.username}",
        )
        rows.append([url_btn(t("pay.card_btn", amount=f"{settings.liqpay_amount:g}", currency=settings.liqpay_currency), url)])
    sub = access.sub
    if sub and sub.provider in ("stars", "liqpay") and sub.current_period_end > utcnow():
        if sub.status == "active":
            rows.append([btn(t("pay.cancel_btn"), Bl(a="cancel"))])
        elif sub.status == "cancelled" and sub.provider == "stars":
            rows.append([btn(t("pay.resume_btn"), Bl(a="resume"))])
    rows.append([btn(t("btn.back"), St(a="back"))])
    return "\n".join(lines), markup(rows)


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, bot: Bot, session: AsyncSession, user: User, settings: Settings) -> None:
    text, kb = await billing_view(bot, session, user, settings)
    await message.answer(text, reply_markup=kb)


@router.callback_query(Bl.filter(F.a == "open"))
async def bl_open(cb: CallbackQuery, bot: Bot, session: AsyncSession, user: User, settings: Settings) -> None:
    await cb.answer()
    text, kb = await billing_view(bot, session, user, settings)
    await bot.send_message(cb.from_user.id, text, reply_markup=kb)


@router.callback_query(Bl.filter(F.a.in_({"cancel", "cancelok", "resume"})))
async def bl_cancel(cb: CallbackQuery, callback_data: Bl, bot: Bot, session: AsyncSession, user: User, settings: Settings) -> None:
    sub = await get_subscription(session, user.id)
    if sub is None or sub.provider not in ("stars", "liqpay"):
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    if callback_data.a == "cancel":
        await cb.answer()
        kb = markup([[btn(t("pay.cancel_yes"), Bl(a="cancelok"))], [btn(t("btn.back"), Bl(a="open"))]])
        if cb.message:
            await cb.message.edit_text(t("pay.cancel_confirm"), reply_markup=kb)
        return
    try:
        if sub.provider == "stars" and sub.provider_sub_id:
            await bot.edit_user_star_subscription(
                user_id=user.tg_id, telegram_payment_charge_id=sub.provider_sub_id,
                is_canceled=callback_data.a == "cancelok",
            )
        elif sub.provider == "liqpay" and sub.provider_sub_id and callback_data.a == "cancelok":
            client = liqpay_client(settings)
            if client is not None:
                await client.unsubscribe(sub.provider_sub_id)
    except Exception as e:  # noqa: BLE001 - payment providers may fail in many ways
        log.warning("subscription change failed: %s", e)
        await cb.answer(t("pay.change_failed"), show_alert=True)
        return
    sub.status = "cancelled" if callback_data.a == "cancelok" else "active"
    await session.flush()
    await cb.answer()
    local = sub.current_period_end.astimezone(tz_of(user.tz))
    key = "pay.cancelled" if callback_data.a == "cancelok" else "pay.resumed"
    if cb.message:
        await cb.message.edit_text(t(key, date=fmt_date(local.date(), user.lang)))


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery, session: AsyncSession) -> None:
    user_id = parse_payload(query.invoice_payload)
    user = await session.get(User, user_id) if user_id else None
    if query.currency != "XTR" or user is None or user.tg_id != query.from_user.id:
        await query.answer(ok=False, error_message=t("pay.invalid"))
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message, session: AsyncSession, user: User) -> None:
    sp = message.successful_payment
    user_id = parse_payload(sp.invoice_payload) or user.id
    is_new = await record_payment(
        session,
        user_id=user_id,
        provider="stars",
        amount=float(sp.total_amount),
        currency=sp.currency,
        provider_payment_id=f"stars:{sp.telegram_payment_charge_id}",
        status="paid",
        raw=sp.model_dump(mode="json"),
    )
    if not is_new:
        return
    existing = await get_subscription(session, user_id)
    charge_for_sub = (
        sp.telegram_payment_charge_id
        if sp.is_first_recurring or existing is None or existing.provider != "stars" or not existing.provider_sub_id
        else None
    )
    until = (
        datetime.fromtimestamp(sp.subscription_expiration_date, tz=timezone.utc)
        if sp.subscription_expiration_date
        else None
    )
    sub = await extend_subscription(
        session, user_id, "stars", until=until, days=None if until else 30, provider_sub_id=charge_for_sub
    )
    analytics.track(session, user_id, "payment", provider="stars", amount=sp.total_amount)
    local = sub.current_period_end.astimezone(tz_of(user.tz))
    await message.answer(t("pay.success", date=fmt_date(local.date(), user.lang)))


@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message, settings: Settings) -> None:
    await message.answer(t("pay.support", contact=html.escape(settings.support_contact or "—")))


@router.message(Command("terms"))
async def cmd_terms(message: Message, settings: Settings) -> None:
    await message.answer(
        t("pay.terms", days=settings.trial_days, usd=f"{settings.sub_price_usd:g}", stars=settings.stars_price)
    )
