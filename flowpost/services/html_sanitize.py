"""Sanitize HTML into the subset supported by Telegram's HTML parse mode."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

_SIMPLE = {
    "b": "b", "strong": "b",
    "i": "i", "em": "i",
    "u": "u", "ins": "u",
    "s": "s", "strike": "s", "del": "s",
    "code": "code", "pre": "pre",
    "tg-spoiler": "tg-spoiler",
}
_BLOCK_BREAK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol"}
_HEADERS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []

    def _open(self, tag: str, attrs: str = "") -> None:
        self.out.append(f"<{tag}{attrs}>")
        self.stack.append(tag)

    def _close(self, tag: str) -> None:
        if tag not in self.stack:
            return
        while self.stack:
            top = self.stack.pop()
            self.out.append(f"</{top}>")
            if top == tag:
                break

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in _SIMPLE:
            self._open(_SIMPLE[tag])
        elif tag in _HEADERS:
            self._open("b")
        elif tag == "a" and a.get("href"):
            href = a["href"].strip()
            if re.match(r"^(https?://|tg://|mailto:)", href, re.IGNORECASE):
                self._open("a", f' href="{html.escape(href, quote=True)}"')
            else:
                self.stack.append("__skip_a")
        elif tag == "blockquote":
            self._open("blockquote", " expandable" if "expandable" in a else "")
        elif tag == "span" and (a.get("class") or "") == "tg-spoiler":
            self._open("tg-spoiler")
        elif tag == "tg-emoji" and a.get("emoji-id"):
            self._open("tg-emoji", f' emoji-id="{html.escape(a["emoji-id"], quote=True)}"')
        elif tag == "br":
            self.out.append("\n")
        elif tag == "li":
            self.out.append("• ")

    def handle_endtag(self, tag):
        if tag in _SIMPLE:
            self._close(_SIMPLE[tag])
        elif tag in _HEADERS:
            self._close("b")
            self.out.append("\n")
        elif tag == "a":
            if self.stack and self.stack[-1] == "__skip_a":
                self.stack.pop()
            else:
                self._close("a")
        elif tag in ("blockquote", "tg-emoji"):
            self._close(tag)
        elif tag == "span":
            if "tg-spoiler" in self.stack:
                self._close("tg-spoiler")
        elif tag == "li":
            self.out.append("\n")
        elif tag in _BLOCK_BREAK:
            self.out.append("\n\n")

    def handle_data(self, data):
        self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        while self.stack:
            top = self.stack.pop()
            if not top.startswith("__"):
                self.out.append(f"</{top}>")
        return "".join(self.out)


# Premium (custom) emoji: `<tg-emoji emoji-id="5368324170671202286">👍</tg-emoji>`. The character inside
# the tag is the plain fallback Telegram itself carries, so dropping the tag degrades gracefully.
_CUSTOM_EMOJI_TAG = re.compile(r"</?tg-emoji\b[^>]*>", re.IGNORECASE)


def has_custom_emoji(text_html: str) -> bool:
    return bool(_CUSTOM_EMOJI_TAG.search(text_html or ""))


def strip_custom_emoji(text_html: str) -> str:
    """Leave only the plain fallback emoji, for bots that may not send custom emoji."""
    return _CUSTOM_EMOJI_TAG.sub("", text_html or "")


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", text, re.DOTALL)
    return m.group(1) if m else text


def sanitize_html(text: str) -> str:
    parser = _Sanitizer()
    parser.feed(_strip_fences(text))
    parser.close()
    result = parser.result()
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


class _TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)


def html_to_plain(text: str) -> str:
    parser = _TextOnly()
    parser.feed(text or "")
    parser.close()
    return "".join(parser.parts)


def visible_len(text_html: str) -> int:
    """Length as Telegram counts it (UTF-16 code units of the text after entity parsing)."""
    plain = html_to_plain(text_html)
    return len(plain.encode("utf-16-le")) // 2


def snippet(text_html: str, limit: int = 40) -> str:
    plain = " ".join(html_to_plain(text_html).split())
    return plain if len(plain) <= limit else plain[: limit - 1].rstrip() + "…"
