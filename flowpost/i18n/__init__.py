"""Tiny key-based i18n: `t("key", **params)` in the current user's language (uk/en)."""
from __future__ import annotations

from contextvars import ContextVar

from . import en, uk

LANGS = ("uk", "en")
LANG_TITLES = {"uk": "🇺🇦 Українська", "en": "🇬🇧 English"}
_TABLES: dict[str, dict[str, str]] = {"uk": uk.TEXTS, "en": en.TEXTS}
_current: ContextVar[str] = ContextVar("flowpost_locale", default="uk")


def set_locale(lang: str | None) -> None:
    _current.set(lang if lang in _TABLES else "uk")


def get_locale() -> str:
    return _current.get()


def t(key: str, locale: str | None = None, **params) -> str:
    """Translate `key`. All strings go through str.format, so literal braces are written as {{ }}."""
    table = _TABLES.get(locale or _current.get(), uk.TEXTS)
    template = table.get(key) or uk.TEXTS.get(key) or key
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        return template


def variants(key: str) -> set[str]:
    """All translations of a key — for matching reply-keyboard buttons in any language."""
    return {table[key] for table in _TABLES.values() if key in table}


def detect_lang(language_code: str | None, default: str = "uk") -> str:
    code = (language_code or "").lower()
    if code.startswith(("uk", "ru", "be")):
        return "uk"
    if code:
        return "en"
    return default if default in _TABLES else "uk"
