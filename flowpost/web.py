"""aiohttp app: health check, the LiqPay server-to-server callback and the billing Mini App."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiohttp import web
from sqlalchemy.ext.asyncio import async_sessionmaker

from flowpost.config import Settings
from flowpost.db.models import User
from flowpost.i18n import t
from flowpost.services import analytics
from flowpost.services.billing.liqpay import (
    CANCEL_STATUSES,
    FAIL_STATUSES,
    PAID_STATUSES,
    LiqPayClient,
    user_id_from_order,
)
from flowpost.services.billing.subscriptions import extend_subscription, get_subscription, record_payment
from flowpost.services.slots import fmt_date, tz_of
from flowpost.webapp import BOT_KEY, SESSIONMAKER_KEY, SETTINGS_KEY
from flowpost.webapp.api import setup_webapp

log = logging.getLogger(__name__)


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def process_liqpay_payload(payload: dict, sessionmaker: async_sessionmaker, bot: Bot | None) -> str:
    """Apply a verified LiqPay callback. Returns what happened (for logs/tests)."""
    status = str(payload.get("status") or "")
    order_id = str(payload.get("order_id") or "")
    user_id = user_id_from_order(order_id)
    if user_id is None:
        return "ignored"
    async with sessionmaker() as session:
        user = await session.get(User, user_id)
        if user is None:
            return "ignored"
        message: str | None = None
        result = "ignored"
        if status in PAID_STATUSES:
            # LiqPay reuses order_id across a subscription's initial charge and every renewal, so
            # falling back to it alone on a missing payment_id would collapse a real renewal into
            # a "duplicate" of an earlier charge and silently skip extending the subscription.
            # create_date (the transaction's own creation timestamp) is present on every callback
            # and is distinct per charge, so prefer that over order_id as the fallback.
            payment_ref = payload.get("payment_id") or payload.get("create_date") or order_id
            is_new = await record_payment(
                session,
                user_id=user_id,
                provider="liqpay",
                amount=float(payload.get("amount") or 0),
                currency=str(payload.get("currency") or ""),
                provider_payment_id=f"liqpay:{payment_ref}",
                status=status,
                raw=payload,
            )
            if is_new:
                sub = await extend_subscription(session, user_id, "liqpay", days=30, provider_sub_id=order_id)
                analytics.track(session, user_id, "payment", provider="liqpay", amount=payload.get("amount"))
                local = sub.current_period_end.astimezone(tz_of(user.tz))
                message = t("pay.success", locale=user.lang, date=fmt_date(local.date(), user.lang))
                result = "extended"
            else:
                result = "duplicate"
        elif status in CANCEL_STATUSES:
            sub = await get_subscription(session, user_id)
            if sub is not None and sub.provider == "liqpay":
                sub.status = "cancelled"
                local = sub.current_period_end.astimezone(tz_of(user.tz))
                message = t("pay.cancelled", locale=user.lang, date=fmt_date(local.date(), user.lang))
                result = "cancelled"
        elif status in FAIL_STATUSES:
            message = t("pay.failed", locale=user.lang)
            result = "failed"
        await session.commit()
    if message and bot is not None:
        try:
            await bot.send_message(user.tg_id, message)
        except TelegramAPIError as e:
            log.info("liqpay notify failed: %s", e)
    return result


async def liqpay_callback(request: web.Request) -> web.Response:
    settings = request.app[SETTINGS_KEY]
    if not settings.liqpay_enabled:
        return web.Response(status=404)
    form = await request.post()
    client = LiqPayClient(
        settings.liqpay_public_key, settings.liqpay_private_key.get_secret_value(), settings.liqpay_sandbox
    )
    payload = client.parse_callback(str(form.get("data") or ""), str(form.get("signature") or ""))
    if payload is None:
        log.warning("LiqPay callback with invalid signature")
        return web.Response(status=400, text="invalid signature")
    result = await process_liqpay_payload(payload, request.app[SESSIONMAKER_KEY], request.app[BOT_KEY])
    log.info("LiqPay callback %s/%s: %s", payload.get("status"), payload.get("order_id"), result)
    return web.Response(text="ok")


def build_web_app(settings: Settings, bot: Bot, sessionmaker: async_sessionmaker) -> web.Application:
    app = web.Application()
    app[SETTINGS_KEY] = settings
    app[BOT_KEY] = bot
    app[SESSIONMAKER_KEY] = sessionmaker
    app.router.add_get("/health", health)
    app.router.add_post("/pay/liqpay/callback", liqpay_callback)
    if settings.webapp_enabled:
        setup_webapp(app)
    return app
