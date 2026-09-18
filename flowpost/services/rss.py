"""RSS/Atom sources: fetching a feed safely from a user-given URL and turning its items into post texts."""
from __future__ import annotations

import asyncio
import html
import ipaddress
import re
import socket
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import aiohttp
import aiohttp.abc

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
TIMEOUT = aiohttp.ClientTimeout(total=20)
MAX_SEEN = 200  # item ids remembered per feed
SUMMARY_CHARS = 700
HEADERS = {"User-Agent": "FlowPostBot/1.0 (+https://t.me/)", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}


class FeedError(Exception):
    """A feed that can't be used; `key` is an i18n key for the owner."""

    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


@dataclass
class FeedItem:
    id: str
    title: str
    link: str
    summary: str


@dataclass
class ParsedFeed:
    title: str
    items: list[FeedItem]  # newest first, as feeds list them


def _public_address(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            return False
    return bool(infos)


async def _check_url(url: str) -> None:
    """Only public http(s) addresses: the server must never be tricked into fetching its own network."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FeedError("rss.err_url")
    if not await asyncio.to_thread(_public_address, parsed.hostname):
        raise FeedError("rss.err_url")


class _PublicResolver(aiohttp.abc.AbstractResolver):
    """Resolves only to public addresses, so a name that changes its answer after `_check_url` still can't point
    the request at the server's own network."""

    def __init__(self) -> None:
        self._inner = aiohttp.DefaultResolver()

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> list:
        infos = await self._inner.resolve(host, port, family)
        if not infos or any(not ipaddress.ip_address(i["host"]).is_global for i in infos):
            raise OSError(f"{host} doesn't resolve to a public address")
        return infos

    async def close(self) -> None:
        await self._inner.close()


async def fetch(url: str) -> bytes:
    """Download a feed, re-checking every redirect target and capping the size."""
    connector = aiohttp.TCPConnector(resolver=_PublicResolver())
    async with aiohttp.ClientSession(timeout=TIMEOUT, headers=HEADERS, connector=connector) as http:
        for _ in range(MAX_REDIRECTS + 1):
            await _check_url(url)
            try:
                async with http.get(url, allow_redirects=False) as resp:
                    if resp.status in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                        url = urljoin(url, resp.headers["Location"])
                        continue
                    if resp.status != 200:
                        raise FeedError("rss.err_fetch")
                    body = await resp.content.read(MAX_BYTES + 1)
                    if len(body) > MAX_BYTES:
                        raise FeedError("rss.err_too_big")
                    return body
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise FeedError("rss.err_fetch") from e
    raise FeedError("rss.err_fetch")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child(el: ET.Element, *names: str) -> ET.Element | None:
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def _text(el: ET.Element | None) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def plain(markup: str) -> str:
    """Feed summaries are HTML; keep only the words."""
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", markup, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def parse(data: bytes) -> ParsedFeed:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise FeedError("rss.err_parse") from e
    kind = _local(root.tag)
    if kind == "rss":
        channel = _child(root, "channel")
        if channel is None:
            raise FeedError("rss.err_parse")
        container, entries = channel, [c for c in channel if _local(c.tag) == "item"]
    elif kind == "feed":
        container, entries = root, [c for c in root if _local(c.tag) == "entry"]
    elif kind == "rdf":
        channel = _child(root, "channel")
        container, entries = channel if channel is not None else root, [c for c in root if _local(c.tag) == "item"]
    else:
        raise FeedError("rss.err_parse")

    items = []
    for entry in entries:
        link_el = _child(entry, "link")
        link = ""
        if link_el is not None:
            link = (link_el.get("href") or _text(link_el)).strip()
        title = plain(_text(_child(entry, "title")))
        summary = plain(_text(_child(entry, "description", "summary", "content", "encoded")))
        ident = _text(_child(entry, "guid", "id")) or link or title
        if ident and (title or summary):
            items.append(FeedItem(id=ident[:300], title=title, link=link, summary=summary))
    return ParsedFeed(title=plain(_text(_child(container, "title")))[:256], items=items)


def item_source(item: FeedItem) -> str:
    """What the AI rewrite gets: the item as plain text."""
    lines = [item.title, "", item.summary[:3000]]
    if item.link:
        lines += ["", item.link]
    return "\n".join(lines).strip()


def item_post(item: FeedItem, read_more: str) -> str:
    """The item as a post without AI: bold title, trimmed summary, link."""
    chunks = []
    if item.title:
        chunks.append(f"<b>{html.escape(item.title)}</b>")
    summary = item.summary
    if len(summary) > SUMMARY_CHARS:
        summary = summary[:SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"
    if summary and summary != item.title:
        chunks.append(html.escape(summary))
    if item.link.startswith(("http://", "https://")):
        chunks.append(f'<a href="{html.escape(item.link, quote=True)}">{html.escape(read_more)}</a>')
    return "\n\n".join(chunks)


def new_items(feed_seen: list[str], items: list[FeedItem], limit: int) -> tuple[list[FeedItem], list[str]]:
    """The oldest `limit` items not handled yet, oldest first, and the updated list of handled ids."""
    seen = set(feed_seen)
    unseen = [i for i in items if i.id not in seen]
    fresh = list(reversed(unseen[-limit:])) if limit > 0 else []
    handled = seen | {i.id for i in fresh}
    updated = [i.id for i in items if i.id in handled]
    updated += [s for s in feed_seen if s not in set(updated)]
    return fresh, updated[:MAX_SEEN]
