"""Parsers for user input: inline buttons, time of day, intervals, topic links."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time

MAX_BUTTON_TEXT = 64
MAX_BUTTON_ROWS = 10
MAX_BUTTONS_PER_ROW = 4


class ParseError(ValueError):
    """Raised with a translation key and optional format params."""

    def __init__(self, key: str, **params):
        super().__init__(key)
        self.key = key
        self.params = params


_SEPARATOR = re.compile(r"\s*[—–]\s*|\s+-\s+")
_URL_OK = re.compile(r"^(https?://[^\s/$.?#][^\s]*|tg://\S+)$", re.IGNORECASE)


def normalize_url(url: str) -> str | None:
    url = url.strip()
    if re.match(r"^(t\.me|telegram\.me)/", url, re.IGNORECASE) or re.match(r"^[\w-]+(\.[\w-]+)+(/\S*)?$", url):
        url = "https://" + url
    if url.startswith("@") and len(url) > 1:
        url = "https://t.me/" + url[1:]
    return url if _URL_OK.match(url) else None


def parse_buttons(raw: str) -> list[list[dict]]:
    """Parse 'Text — URL' lines. Each line is a row, '|' splits buttons inside a row."""
    rows: list[list[dict]] = []
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        raise ParseError("err.buttons_empty")
    for line_no, line in enumerate(lines, start=1):
        row: list[dict] = []
        for chunk in (c.strip() for c in line.split("|")):
            if not chunk:
                continue
            separators = list(_SEPARATOR.finditer(chunk))
            if not separators:
                raise ParseError("err.buttons_format", line=line_no)
            last = separators[-1]  # the button text itself may contain dashes
            text = chunk[:last.start()].strip()
            raw_url = chunk[last.end():].strip()
            url = normalize_url(raw_url) if raw_url and " " not in raw_url else None
            if not text or len(text) > MAX_BUTTON_TEXT:
                raise ParseError("err.buttons_text", line=line_no, max=MAX_BUTTON_TEXT)
            if not url:
                raise ParseError("err.buttons_url", line=line_no)
            row.append({"text": text, "url": url})
        if not row:
            continue
        if len(row) > MAX_BUTTONS_PER_ROW:
            raise ParseError("err.buttons_row", line=line_no, max=MAX_BUTTONS_PER_ROW)
        rows.append(row)
    if len(rows) > MAX_BUTTON_ROWS:
        raise ParseError("err.buttons_rows", max=MAX_BUTTON_ROWS)
    return rows


def buttons_to_text(rows: list[list[dict]]) -> str:
    return "\n".join(" | ".join(f"{b['text']} — {b['url']}" for b in row) for row in rows)


_TIME_RE = re.compile(r"^\s*(\d{1,2})\s*[:.\s,\-]\s*(\d{2})\s*$")


def parse_time(raw: str) -> time:
    m = _TIME_RE.match(raw or "")
    if not m:
        raise ParseError("err.time_format")
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ParseError("err.time_format")
    return time(hour, minute)


def parse_positive_int(raw: str, max_value: int) -> int:
    raw = (raw or "").strip()
    if not raw.isdigit():
        raise ParseError("err.number", max=max_value)
    value = int(raw)
    if not 1 <= value <= max_value:
        raise ParseError("err.number", max=max_value)
    return value


@dataclass
class TopicRef:
    topic_id: int | None


_TOPIC_LINK = re.compile(r"t\.me/(?:c/\d+|[\w\d_]+)/(\d+)", re.IGNORECASE)


def parse_topic(raw: str) -> TopicRef:
    raw = (raw or "").strip()
    if raw.isdigit():
        return TopicRef(int(raw))
    m = _TOPIC_LINK.search(raw)
    if not m:
        raise ParseError("err.topic")
    return TopicRef(int(m.group(1)))
