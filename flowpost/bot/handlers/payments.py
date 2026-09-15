"""Telegram Stars wallet top-ups: pre-checkout validation and crediting the paid amount."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.config import Settings
from flowpost.db.models import User
from flowpost.i18n import t
from flowpost.services.billing.stars import CURRENCY, parse_payload
from flowpost.services.billing.wallet import apply_topup

router = Router(name="payments")


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery, session: AsyncSession, settings: Settings) -> None:
    parsed = parse_payload(query.invoice_payload)
    owner = await session.get(User, parsed[0]) if parsed else None
    valid = (
        parsed is not None
        and owner is not None
        and owner.tg_id == query.from_user.id
        and query.currency == CURRENCY
        and query.total_amount == parsed[1]
        and settings.stars_topup_min <= parsed[1] <= settings.stars_topup_max
    )
    if not valid:
        await query.answer(ok=False, error_message=t("pay.invalid"))
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message, session: AsyncSession, user: User, settings: Settings) -> None:
    sp = message.successful_payment
    if sp.currency != CURRENCY or parse_payload(sp.invoice_payload) is None:
        return
    bonus = await apply_topup(
        session, user.id, sp.total_amount, sp.telegram_payment_charge_id, sp.model_dump(mode="json"),
        settings.cashback_percent,
    )
    if bonus is None:
        return
    key = "pay.topup_done_cashback" if bonus else "pay.topup_done"
    await message.answer(t(key, stars=sp.total_amount, cashback=bonus, balance=user.balance))
