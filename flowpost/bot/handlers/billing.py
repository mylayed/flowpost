"""Subscription: LiqPay card checkout, manual bank transfer, /paysupport, /terms."""
from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Bl, St
from flowpost.bot.handlers.settings import access_line
from flowpost.bot.keyboards.common import btn, markup, url_btn
from flowpost.bot.states import Billing
from flowpost.config import Settings
from flowpost.db.models import User
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services.billing.liqpay import LiqPayClient
from flowpost.services.billing.subscriptions import get_access, get_subscription
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
        t("pay.price", usd=f"{settings.sub_price_usd:g}"),
        access_line(access, user),
    ]
    rows = []
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
    if settings.payment_requisites:
        rows.append([btn(t("pay.manual_btn"), Bl(a="manual"))])
    sub = access.sub
    if sub and sub.provider == "liqpay" and sub.status == "active" and sub.current_period_end > utcnow():
        rows.append([btn(t("pay.cancel_btn"), Bl(a="cancel"))])
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


def _requisites_html(raw: str) -> str:
    """Render each "Label: value" line with only the value in a tap-to-copy <code> span."""
    lines = []
    for line in raw.splitlines():
        label, sep, value = line.partition(":")
        if sep and value.strip():
            lines.append(f"{html.escape(label.strip())}: <code>{html.escape(value.strip())}</code>")
        else:
            lines.append(html.escape(line))
    return "\n".join(lines)


@router.callback_query(Bl.filter(F.a == "manual"))
async def bl_manual(cb: CallbackQuery, bot: Bot, state: FSMContext, settings: Settings) -> None:
    await cb.answer()
    if not settings.payment_requisites:
        return
    await state.set_state(Billing.manual_receipt)
    kb = markup([[btn(t("btn.back"), Bl(a="open"))]])
    await bot.send_message(
        cb.from_user.id, t("pay.manual_info", requisites=_requisites_html(settings.payment_requisites)), reply_markup=kb
    )


@router.message(Billing.manual_receipt, F.photo | F.document)
async def in_manual_receipt(message: Message, bot: Bot, state: FSMContext, user: User, settings: Settings) -> None:
    await state.clear()
    name = html.escape(message.from_user.full_name if message.from_user else str(user.tg_id))
    username = f" @{message.from_user.username}" if message.from_user and message.from_user.username else ""
    caption = t("pay.manual_admin_caption", name=name, tg_id=user.tg_id, username=username)
    for admin_id in settings.admin_id_set:
        try:
            await bot.forward_message(admin_id, from_chat_id=message.chat.id, message_id=message.message_id)
            await bot.send_message(admin_id, caption)
        except TelegramAPIError as e:
            log.warning("failed to forward receipt to admin %s: %s", admin_id, e)
    await message.answer(t("pay.manual_sent"))


@router.message(Billing.manual_receipt)
async def in_manual_wrong(message: Message) -> None:
    await message.answer(t("pay.manual_wrong"))


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
    await message.answer(t("pay.terms", days=settings.trial_days, usd=f"{settings.sub_price_usd:g}"))
