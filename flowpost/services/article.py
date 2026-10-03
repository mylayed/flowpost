"""The readable text of a web article from a user-given link, for «Серія з довгого тексту»."""
from __future__ import annotations

import html
import re

from flowpost.services import rss

MAX_CHARS = 40000
_CLUTTER = re.compile(r"<(script|style|noscript|svg|nav|header|footer|aside|form|template)\b.*?</\1\s*>", re.S | re.I)
_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([\w-]+)""", re.I)


class ArticleError(Exception):
    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


def _decode(body: bytes) -> str:
    match = _CHARSET.search(body[:4096])
    for encoding in ((match.group(1).decode("ascii", "ignore"),) if match else ()) + ("utf-8", "cp1251"):
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def extract(page: str) -> str:
    """Title plus the main text: the <article> (or <main>, or <body>) without menus, scripts and other clutter."""
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    page = _CLUTTER.sub(" ", re.sub(r"<!--.*?-->", " ", page, flags=re.S))
    for tag in ("article", "main", "body"):
        found = re.findall(rf"<{tag}\b[^>]*>(.*?)</{tag}\s*>", page, re.S | re.I)
        if found:
            page = "\n".join(found)
            break
    text = rss.plain(re.sub(r"</(h[1-6]|li|div|section|blockquote|tr)>", "\n", page, flags=re.I))
    head = html.unescape(re.sub(r"\s+", " ", title.group(1))).strip() if title else ""
    if head and not text.startswith(head):
        text = f"{head}\n\n{text}"
    return text[:MAX_CHARS].strip()


async def fetch_text(url: str) -> str:
    try:
        body = await rss.fetch(url)
    except rss.FeedError as e:
        raise ArticleError("series.err_too_big" if e.key == "rss.err_too_big" else "series.err_fetch") from e
    text = extract(_decode(body))
    if len(text) < 300:
        raise ArticleError("series.err_no_text")
    return text
