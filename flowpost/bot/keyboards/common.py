from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from flowpost.bot.callbacks import Bl, Pj
from flowpost.i18n import t


def btn(text: str, cb: CallbackData | str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb.pack() if isinstance(cb, CallbackData) else cb)


def url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def markup(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])


def on(flag: bool) -> str:
    return "✅ " if flag else ""


def chunked(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def paywall_kb() -> InlineKeyboardMarkup:
    return markup([[btn(t("btn.pay"), Bl(a="open"))]])


def add_channel_inline_kb() -> InlineKeyboardMarkup:
    return markup([[btn(t("btn.add_channel"), Pj(a="add"))]])
