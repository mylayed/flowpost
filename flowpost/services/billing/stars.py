"""Telegram Stars wallet top-ups: invoice links and their payloads."""
from __future__ import annotations

from aiogram import Bot
from aiogram.types import LabeledPrice

from flowpost.i18n import t

CURRENCY = "XTR"
PAYLOAD_PREFIX = "fp-topup"


def make_payload(user_id: int, stars: int) -> str:
    return f"{PAYLOAD_PREFIX}:{user_id}:{stars}"


def parse_payload(payload: str | None) -> tuple[int, int] | None:
    parts = (payload or "").split(":")
    if len(parts) != 3 or parts[0] != PAYLOAD_PREFIX or not (parts[1].isdigit() and parts[2].isdigit()):
        return None
    return int(parts[1]), int(parts[2])


async def create_topup_link(bot: Bot, user_id: int, stars: int, lang: str) -> str:
    return await bot.create_invoice_link(
        title=t("pay.topup_title", locale=lang),
        description=t("pay.topup_desc", locale=lang, stars=stars),
        payload=make_payload(user_id, stars),
        currency=CURRENCY,
        prices=[LabeledPrice(label="Stars", amount=stars)],
    )
