"""Telegram Stars monthly subscription (createInvoiceLink with subscription_period)."""
from __future__ import annotations

from aiogram import Bot
from aiogram.types import LabeledPrice

from flowpost.config import Settings
from flowpost.i18n import t

SUBSCRIPTION_PERIOD = 2592000  # 30 days — the only period Telegram currently allows
PAYLOAD_PREFIX = "flowpost-sub"


def make_payload(user_id: int) -> str:
    return f"{PAYLOAD_PREFIX}:{user_id}"


def parse_payload(payload: str | None) -> int | None:
    prefix, _, user_id = (payload or "").partition(":")
    if prefix == PAYLOAD_PREFIX and user_id.isdigit():
        return int(user_id)
    return None


async def create_subscription_link(bot: Bot, user_id: int, settings: Settings, lang: str) -> str:
    return await bot.create_invoice_link(
        title=t("pay.stars_title", locale=lang),
        description=t("pay.stars_desc", locale=lang, days=30),
        payload=make_payload(user_id),
        currency="XTR",
        prices=[LabeledPrice(label="FlowPost Pro", amount=settings.stars_price)],
        subscription_period=SUBSCRIPTION_PERIOD,
    )
