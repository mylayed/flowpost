"""Ad posts: the «top» hours of an ad's format, booked slots, the post an ad answers, vetting an ad before it goes
out and the numbers of the report on it for the advertiser."""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Channel, Post, Publication, User
from flowpost.i18n import t
from flowpost.services import analytics, rss
from flowpost.services.ai import AIError, AIService
from flowpost.services.billing import limits
from flowpost.services.html_sanitize import snippet
from flowpost.services.posts import AD_FORMATS, message_link, options_of, part_preview_text
from flowpost.services.slots import fmt_date, fmt_hm, tz_of

MAX_TOP_HOURS = max(top for top, _ in AD_FORMATS.values())
ADVERTISER_MAX = 64
_LINK = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(?:c/(\d+)|([A-Za-z0-9_]{4,}))/(\d+)", re.I)


def is_booking(post: Post) -> bool:
    return post.is_ad and bool(options_of(post).get("ad_booking"))


def format_of(post: Post) -> tuple[int, int] | None:
    """(top hours, feed hours) of the ad's format, or None when it has none."""
    return AD_FORMATS.get(options_of(post).get("ad_format") or 0)


async def top_until(session: AsyncSession, channel_id: int, now: datetime) -> datetime | None:
    """While an ad published in the channel is still in its «top» hours, the moment they end."""
    rows = (await session.execute(
        select(Publication.published_at, Post.options)
        .join(Post, Post.id == Publication.post_id)
        .where(
            Publication.channel_id == channel_id,
            Publication.status == "published",
            Publication.published_at > now - timedelta(hours=MAX_TOP_HOURS),
            Post.is_ad.is_(True),
        )
    )).all()
    ends = [
        published_at + timedelta(hours=AD_FORMATS[(options or {}).get("ad_format")][0])
        for published_at, options in rows
        if published_at is not None and (options or {}).get("ad_format") in AD_FORMATS
    ]
    end = max(ends, default=None)
    return end if end is not None and end > now else None


def looks_like_advertiser(text: str) -> bool:
    """A booking gets either the ad itself or just who's buying it: a short single line is taken for a name."""
    text = (text or "").strip()
    return bool(text) and "\n" not in text and len(text) <= ADVERTISER_MAX and "://" not in text


def parse_post_link(text: str, channels: list[Channel]) -> tuple[Channel, int] | None:
    """The channel among `channels` and the message id a t.me post link points to."""
    m = _LINK.search(text or "")
    if m is None:
        return None
    internal, username, message_id = m.groups()
    for channel in channels:
        if internal and str(channel.chat_id) == f"-100{internal}":
            return channel, int(message_id)
        if username and channel.username and channel.username.lower() == username.lower():
            return channel, int(message_id)
    return None


# ---- «🛡 Перевірити рекламу» --------------------------------------------------------------------------------------

MAX_CHECK_LINKS = 5
_HREF = re.compile(r'href="([^"]+)"')
_BARE_URL = re.compile(r"https?://[^\s<>\"']+")
PROBE_TIMEOUT = aiohttp.ClientTimeout(total=10)
SHORTENERS = {"bit.ly", "tinyurl.com", "cutt.ly", "goo.su", "clck.ru", "t.ly", "is.gd", "rebrand.ly", "shorturl.at"}


def content_hash(post: Post) -> str:
    """What a check result belongs to: the ad's texts and buttons. A changed ad has to be checked again."""
    raw = json.dumps(
        [[part.text_html, part.buttons or [], [m.get("uid") for m in part.media or []]] for part in post.parts],
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha1(raw.encode()).hexdigest()


def ad_links(post: Post) -> list[str]:
    """The ad's links, from its text and its buttons, each once."""
    found: list[str] = []
    for part in post.parts:
        text = part.text_html or ""
        for url in _HREF.findall(text) + _BARE_URL.findall(text):
            found.append(html.unescape(url))
        found += [b["url"] for row in part.buttons or [] for b in row if b.get("url")]
    return list(dict.fromkeys(u for u in found if u.startswith(("http://", "https://"))))


async def probe(url: str) -> str:
    """What opening `url` shows, in a few words for the AI: where it ends up, or why it doesn't open."""
    host = (urlparse(url).hostname or "").lower()
    note = "shortener; " if host.removeprefix("www.") in SHORTENERS else ""
    connector = aiohttp.TCPConnector(resolver=rss._PublicResolver())
    try:
        async with aiohttp.ClientSession(timeout=PROBE_TIMEOUT, headers=rss.HEADERS, connector=connector) as http:
            for _ in range(rss.MAX_REDIRECTS + 1):
                await rss._check_url(url)
                async with http.get(url, allow_redirects=False) as resp:
                    if resp.status in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                        url = urljoin(url, resp.headers["Location"])
                        continue
                    if resp.status >= 400:
                        return f"{note}broken: HTTP {resp.status}"
                    return f"{note}opens: {url}"
    except rss.FeedError:
        return f"{note}not a public web address"
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return f"{note}broken: doesn't open"
    return f"{note}broken: too many redirects"


async def check_links(post: Post) -> list[tuple[str, str]]:
    urls = ad_links(post)[:MAX_CHECK_LINKS]
    return list(zip(urls, await asyncio.gather(*(probe(u) for u in urls))))


# ---- «📊 Звіт рекламодавцю» ---------------------------------------------------------------------------------------

REPORT_AFTER = timedelta(hours=24)  # an ad without a delete timer is reported on after a day
_VIEWS = re.compile(r'class="tgme_widget_message_views">([^<]+)<')


def report_due(opts: dict, published_at: datetime) -> datetime:
    """Right before the ad is deleted, while its views can still be read; a day after publishing otherwise."""
    if opts.get("auto_delete_hours"):
        return published_at + timedelta(hours=float(opts["auto_delete_hours"])) - timedelta(minutes=1)
    return published_at + REPORT_AFTER


async def fetch_views(channel: Channel, message_id: int) -> str | None:
    """The post's view count as Telegram shows it («1.2K»): read from its public web preview, so only for public
    channels."""
    if not channel.username:
        return None
    try:
        page = (await rss.fetch(f"https://t.me/{channel.username}/{message_id}?embed=1")).decode("utf-8", "replace")
    except rss.FeedError:
        return None
    m = _VIEWS.search(page)
    return html.unescape(m.group(1)).strip() if m else None


def _reactions(pub: Publication) -> dict[str, int]:
    totals: dict[str, int] = {}
    for per_message in (pub.reactions or {}).values():
        for emoji, count in per_message.items():
            totals[emoji] = totals.get(emoji, 0) + count
    return dict(sorted(totals.items(), key=lambda kv: -kv[1]))


async def build_report(
    session: AsyncSession, bot: Bot, ai: AIService | None, pub: Publication, post: Post, channel: Channel,
    owner: User, now: datetime,
) -> str:
    """The report on how the ad ran, in the owner's language, ready to forward to the advertiser. Its AI conclusion
    costs the channel one AI text; without one left the report goes out with the numbers only."""
    lang = owner.lang
    zone = tz_of(owner.tz)
    opts = options_of(post)
    ids = [i for part in (pub.message_ids or {}).get("parts", []) for i in part.get("ids", [])]
    first = post.parts[0] if post.parts else None
    title = snippet(part_preview_text(first), 60) if first is not None else ""
    title = title or opts.get("ad_advertiser") or t("parts.no_text", locale=lang)
    start = (pub.published_at or now).astimezone(zone)
    end = now.astimezone(zone)
    period = f"{fmt_date(start.date(), lang)} {fmt_hm(start)} — {fmt_date(end.date(), lang)} {fmt_hm(end)}"
    fmt = format_of(post)
    if fmt:
        period += " · " + t("adrep.format", top=fmt[0], feed=fmt[1], locale=lang)

    views = await fetch_views(channel, ids[0]) if ids and not pub.deleted else None
    reactions = _reactions(pub)
    before = (pub.ad_stats or {}).get("members_before")
    try:
        after = await bot.get_chat_member_count(channel.chat_id)
    except TelegramAPIError:
        after = None

    lines = [
        t("adrep.title", channel=html.escape(channel.title, quote=False), locale=lang),
        "",
        t("adrep.ad", title=html.escape(title, quote=False), locale=lang),
        t("adrep.period", period=period, locale=lang),
        t("adrep.views", n=html.escape(views), locale=lang) if views
        else t("adrep.views_private" if not channel.username else "adrep.views_unknown", locale=lang),
    ]
    total = sum(reactions.values())
    detail = ", ".join(f"{emoji} {count}" for emoji, count in list(reactions.items())[:5])
    lines.append(t("adrep.reactions", n=total, locale=lang) + (f" ({detail})" if detail else ""))
    lines.append(t("adrep.comments", n=pub.comments_count or 0, locale=lang))
    if before is not None and after is not None:
        lines.append(t("adrep.members", delta=f"{after - before:+d}", before=before, after=after, locale=lang))
    if ids and not pub.deleted:
        lines.append(t("adrep.link", link=message_link(channel, ids[0]), locale=lang))

    stats = "\n".join([
        f"ran: {(now - (pub.published_at or now)).total_seconds() / 3600:.0f} hours"
        + (f" (format: {fmt[0]} hour(s) at the top, {fmt[1]} hours in the feed)" if fmt else ""),
        f"views: {views or 'unknown'}",
        f"reactions: {total}" + (f" ({detail})" if detail else ""),
        f"comments: {pub.comments_count or 0}",
        f"channel subscribers: {before} before, {after} after" if before is not None and after is not None
        else "channel subscribers: unknown",
    ])
    summary = None
    if ai is not None and ai.enabled:
        if await limits.take(session, channel.id, "ai_text"):
            await session.commit()  # the quota row isn't held for the length of the request
            try:
                summary = await ai.ad_report_summary(first.text_html if first else "", stats, lang=lang)
                analytics.track(session, owner.id, "ai_call", action="ad_report")
            except AIError:
                await limits.add(session, channel.id, "ai_text", 1)
        else:
            lines += ["", t("adrep.no_ai", locale=lang)]
    if summary:
        lines += ["", t("adrep.summary", text=html.escape(summary, quote=False), locale=lang)]
    return "\n".join(lines)
