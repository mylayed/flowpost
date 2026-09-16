from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from flowpost.bot.callbacks import Bl, Pj
from flowpost.config import Settings
from flowpost.i18n import t


def btn(text: str, cb: CallbackData | str, style: str | None = None) -> InlineKeyboardButton:
    """`style` (Bot API 9.4: primary|success|danger) is ignored by clients older than Feb 2026."""
    return InlineKeyboardButton(
        text=text, callback_data=cb.pack() if isinstance(cb, CallbackData) else cb, style=style
    )


def url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def markup(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])


def on(flag: bool) -> str:
    return "✅ " if flag else ""


def chunked(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def pay_btn(settings: Settings, text: str | None = None) -> InlineKeyboardButton:
    """Opens the billing Mini App; without a public HTTPS URL it falls back to the /subscribe screen."""
    label = text or t("btn.pay")
    if settings.webapp_url:
        return InlineKeyboardButton(text=label, web_app=WebAppInfo(url=settings.webapp_url))
    return btn(label, Bl(a="open"))


def paywall_kb(settings: Settings) -> InlineKeyboardMarkup:
    return markup([[pay_btn(settings)]])


def add_channel_inline_kb() -> InlineKeyboardMarkup:
    return markup([[btn(t("btn.add_channel"), Pj(a="add"))]])
