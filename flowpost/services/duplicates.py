"""Warn an admin when a post they're about to publish looks like one already published before."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Channel, Post, PostPart
from flowpost.db.repo import publications as pubs_repo
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services.html_sanitize import snippet
from flowpost.services.posts import message_link, part_preview_text
from flowpost.services.slots import fmt_date, tz_of

LOOKBACK_DAYS = 90
TEXT_MIN_LEN = 20
TEXT_SIMILARITY = 0.85


@dataclass
class DuplicateMatch:
    channel: Channel
    published_at: datetime
    link: str | None
    kind: str  # "text" | "media"


def _norm_text(part: PostPart) -> str:
    return snippet(part_preview_text(part), limit=10_000).lower()


def _media_uids(part: PostPart) -> set[str]:
    return {m["uid"] for m in (part.media or []) if m.get("uid")}


def _part_link(channel: Channel, message_ids: dict, part_index: int) -> str | None:
    parts = (message_ids or {}).get("parts", [])
    if part_index >= len(parts):
        return None
    ids = parts[part_index].get("ids") or []
    return message_link(channel, ids[0]) if ids else None


async def find_duplicates(
    session: AsyncSession, owner_id: int, post: Post, channels: dict[int, Channel]
) -> list[DuplicateMatch]:
    """Compare `post`'s parts against posts already published into `channels` in the last `LOOKBACK_DAYS`."""
    since = utcnow() - timedelta(days=LOOKBACK_DAYS)
    pubs = await pubs_repo.published_between(session, owner_id, since, utcnow(), list(channels))

    new_parts = [(_norm_text(p), _media_uids(p)) for p in post.parts]
    matches: list[DuplicateMatch] = []
    matched_channels: set[tuple[int, str]] = set()

    for pub in pubs:
        if pub.post_id == post.id:
            continue
        channel = channels.get(pub.channel_id)
        if channel is None:
            continue
        old_post = await session.get(Post, pub.post_id)
        if old_post is None:
            continue
        for i, old_part in enumerate(old_post.parts):
            old_text = _norm_text(old_part)
            old_uids = _media_uids(old_part)
            for new_text, new_uids in new_parts:
                text_key = (pub.channel_id, "text")
                if (
                    text_key not in matched_channels
                    and len(new_text) >= TEXT_MIN_LEN
                    and len(old_text) >= TEXT_MIN_LEN
                    and SequenceMatcher(None, new_text, old_text).ratio() >= TEXT_SIMILARITY
                ):
                    matched_channels.add(text_key)
                    matches.append(DuplicateMatch(
                        channel=channel, published_at=pub.published_at,
                        link=_part_link(channel, pub.message_ids, i), kind="text",
                    ))
                media_key = (pub.channel_id, "media")
                if media_key not in matched_channels and new_uids and (new_uids & old_uids):
                    matched_channels.add(media_key)
                    matches.append(DuplicateMatch(
                        channel=channel, published_at=pub.published_at,
                        link=_part_link(channel, pub.message_ids, i), kind="media",
                    ))
    return matches


def warning_lines(matches: list[DuplicateMatch], tz_name: str, lang: str) -> list[str]:
    lines = []
    for m in matches:
        date_str = fmt_date(m.published_at.astimezone(tz_of(tz_name)).date(), lang)
        key = "dup.warn_media" if m.kind == "media" else "dup.warn_text"
        line = t(key, channel=m.channel.title, date=date_str)
        if m.link:
            line += " " + t("dup.warn_link", link=m.link)
        lines.append(line)
    return lines
