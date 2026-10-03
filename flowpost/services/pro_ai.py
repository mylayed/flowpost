"""PRO AI tools of a channel: its voice profile, ad posts from a brief, niche research among competitors and the
comment answerer. Each AI request spends one «ai_text» of the channel, like the other AI texts."""
from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.config import Settings
from flowpost.db.models import Channel, Post, Publication, User
from flowpost.db.types import utcnow
from flowpost.services import analytics, rss
from flowpost.services.billing import limits
from flowpost.services.delivery import engagement_score
from flowpost.services.html_sanitize import html_to_plain

MAX_COMPETITORS = 5
MAX_KB = 4000
VOICE_MIN_POSTS = 5
VOICE_POSTS = 40
NICHE_OWN_POSTS = 15
NICHE_POSTS_PER_CHANNEL = 15
_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
_QUESTION_START = re.compile(
    r"^(як|скільки|де|коли|чи|що|який|яка|яке|які|чому|навіщо|хто|куди|звідки|можна|а можна|підкажіть|"
    r"how|what|where|when|why|who|which|is|are|can|could|do|does|will|"
    r"как|сколько|где|когда|почему|что|какой|можно|подскажите)\b",
    re.I,
)


class ProAIError(Exception):
    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


def tools_settings(raw: dict | None) -> dict:
    return {"answer": False, "kb": "", "answer_out": False, "competitors": [], **(raw or {})}


# ---- spending ---------------------------------------------------------------------------------------------------

async def spend(session: AsyncSession, settings: Settings, user: User, channel: Channel) -> None:
    """Charge the channel one AI text for a request `user` asked for; committed before the long request, so two
    quick taps can't both spend the last one. `refund` gives it back when the request fails."""
    if await analytics.count_since(session, user.id, "ai_call", utcnow() - timedelta(days=1)) >= settings.ai_daily_limit_paid:
        raise ProAIError("ai.quota_over")
    if not await limits.take(session, channel.id, "ai_text"):
        raise ProAIError("ai.quota_channel_over")
    await session.commit()


async def refund(session: AsyncSession, channel_id: int) -> None:
    await limits.add(session, channel_id, "ai_text", 1)
    await session.commit()


# ---- the channel's own posts ------------------------------------------------------------------------------------

async def top_texts(session: AsyncSession, channel: Channel, limit: int, *, days: int = 180) -> list[str]:
    """Texts of the channel's most engaging posts of the last `days`, best first, without repeats."""
    pubs = (await session.scalars(
        select(Publication)
        .where(Publication.channel_id == channel.id, Publication.status == "published",
               Publication.published_at >= utcnow() - timedelta(days=days), Publication.repeat_index == 0)
        .order_by(Publication.published_at.desc())
        .limit(300)
    )).all()
    texts: list[str] = []
    seen: set[int] = set()
    for pub in sorted(pubs, key=engagement_score, reverse=True):
        if pub.post_id in seen:
            continue
        seen.add(pub.post_id)
        post = await session.get(Post, pub.post_id)
        if post is None:
            continue
        text = "\n\n".join(p.text_html.strip() for p in post.parts if p.text_html.strip())
        if len(html_to_plain(text).strip()) >= 40 and text not in texts:
            texts.append(text[:1200])
        if len(texts) >= limit:
            break
    return texts


# ---- competitors' public channels -------------------------------------------------------------------------------

def parse_channel_refs(raw: str) -> list[str]:
    """Usernames from «@name», «t.me/name» or «https://t.me/s/name» separated by spaces, commas or lines."""
    found: list[str] = []
    for token in re.split(r"[\s,;]+", raw.strip()):
        token = re.sub(r"^(https?://)?(www\.)?(t\.me|telegram\.me)/(s/)?", "", token.strip(), flags=re.I)
        token = token.lstrip("@").split("/")[0].split("?")[0]
        if _USERNAME.match(token) and token.lower() not in (f.lower() for f in found):
            found.append(token)
    return found[:MAX_COMPETITORS]


@dataclass
class PublicChannel:
    username: str
    title: str
    posts: list[dict]  # {"text", "views"}, newest last as the page lists them


def parse_public_page(page: str, username: str) -> PublicChannel:
    """Posts of a channel's public web preview (t.me/s/<username>)."""
    title = re.search(r'<meta property="og:title" content="([^"]*)"', page)
    posts = []
    for chunk in page.split('class="tgme_widget_message_wrap')[1:]:
        text = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', chunk, re.S)
        if not text:
            continue
        plain = rss.plain(text.group(1))
        if len(plain) < 20:
            continue
        views = re.search(r'class="tgme_widget_message_views">([^<]+)<', chunk)
        posts.append({"text": plain[:1000], "views": views.group(1).strip() if views else ""})
    return PublicChannel(username, html.unescape(title.group(1)) if title else username, posts)


async def fetch_public_channel(username: str) -> PublicChannel | None:
    """The channel's latest public posts, or None when it has no public preview (private, or turned off)."""
    try:
        page = (await rss.fetch(f"https://t.me/s/{username}")).decode("utf-8", "replace")
    except rss.FeedError:
        return None
    channel = parse_public_page(page, username)
    if not channel.posts:
        return None
    channel.posts = channel.posts[-NICHE_POSTS_PER_CHANNEL:]
    return channel


async def fetch_competitors(usernames: list[str]) -> list[PublicChannel]:
    found = await asyncio.gather(*(fetch_public_channel(u) for u in usernames))
    return [c for c in found if c is not None]


# ---- comment answerer -------------------------------------------------------------------------------------------

def looks_like_question(text: str) -> bool:
    """Only comments that may be questions go to the AI: the rest would just spend AI texts on «skip»."""
    text = text.strip()
    return len(text) >= 6 and ("?" in text or bool(_QUESTION_START.match(text)))


@dataclass
class Question:
    channel_id: int
    chat_id: int
    message_id: int
    thread_id: int | None  # the forum topic, when the discussion group has topics
    text: str
    publication_id: int | None


def comment_link(chat_id: int, message_id: int, thread_id: int | None) -> str | None:
    """A t.me/c link to a comment for the group's members; None for chats without a -100… id."""
    raw = str(chat_id)
    if not raw.startswith("-100"):
        return None
    link = f"https://t.me/c/{raw[4:]}/{message_id}"
    return f"{link}?thread={thread_id}" if thread_id else link
