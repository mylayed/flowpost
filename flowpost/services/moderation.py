"""Comment moderation for discussion groups: profanity, spam links/mentions, and flood control."""
from __future__ import annotations

import re
import time

DEFAULT_MODERATION: dict = {"enabled": True, "banned_words": []}

FLOOD_WINDOW_SECONDS = 60
MAX_BANNED_WORDS = 50

# Common uk/ru profanity roots. Matched as substrings of the normalized (letters-only) text,
# so punctuation inserted between letters ("х.у.й") or repeated letters don't evade it.
BUILT_IN_ROOTS: tuple[str, ...] = (
    "хуй", "хуё", "хуе", "хуи", "пизд", "піздец", "пізд", "єбат", "ебат", "ёбан", "ебан",
    "заєб", "заеб", "уёб", "уеб", "мудак", "мудил", "сука", "сучка", "бляд", "блят",
    "гандон", "підар", "педик", "хер моржовий", "долбоёб", "долбоеб", "хуйн", "хуёв", "хуев",
)

_LINK_RE = re.compile(r"(https?://\S+|t\.me/\S+|telegram\.me/\S+|www\.\S+\.\S+)", re.IGNORECASE)
_MENTION_RE = re.compile(r"@\w{5,}")
_NON_LETTER_RE = re.compile(r"[^0-9a-zA-Zа-яіїєґА-ЯІЇЄҐ]+")


def moderation_settings(raw: dict | None) -> dict:
    return {**DEFAULT_MODERATION, **(raw or {})}


def _normalize(text: str) -> str:
    return _NON_LETTER_RE.sub("", text or "").lower()


def contains_banned_word(text: str, extra_words: list[str]) -> bool:
    norm = _normalize(text)
    if not norm:
        return False
    for word in (*BUILT_IN_ROOTS, *extra_words):
        root = _normalize(word)
        if root and root in norm:
            return True
    return False


def contains_spam_link(text: str) -> bool:
    return bool(_LINK_RE.search(text or "") or _MENTION_RE.search(text or ""))


def is_flood(cache: dict[tuple[int, int], tuple[str, float]], chat_id: int, user_id: int, text: str,
             *, now: float | None = None) -> bool:
    """True if the same (normalized) text was just posted by this user in this chat."""
    now = time.monotonic() if now is None else now
    norm = _normalize(text)
    key = (chat_id, user_id)
    prev = cache.get(key)
    cache[key] = (norm, now)
    if not norm or prev is None:
        return False
    prev_norm, prev_time = prev
    return norm == prev_norm and (now - prev_time) < FLOOD_WINDOW_SECONDS


def violation(
    text: str, extra_words: list[str], flood_cache: dict[tuple[int, int], tuple[str, float]],
    chat_id: int, user_id: int,
) -> str | None:
    """Return a violation kind ("profanity" | "spam_link" | "flood") or None if the message is clean."""
    if contains_banned_word(text, extra_words):
        return "profanity"
    if contains_spam_link(text):
        return "spam_link"
    if is_flood(flood_cache, chat_id, user_id, text):
        return "flood"
    return None
