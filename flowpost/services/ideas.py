"""Content ideas: AI drafts for a channel's coming week, kept as draft posts until they're scheduled.

The AI content plan in the bot shows them once; the calendar Mini App keeps them (a draft post flagged `idea`) so they
can be dragged onto a day and time.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.config import Settings
from flowpost.db.models import Channel, Post, PostTarget, User
from flowpost.db.repo import posts as posts_repo
from flowpost.db.repo import publications as pubs_repo
from flowpost.db.types import utcnow
from flowpost.services import analytics
from flowpost.services.ai import AIError, AIService
from flowpost.services.billing import entitlements, limits
from flowpost.services.delivery import engagement_score
from flowpost.services.posts import channel_defaults, initial_options, part_preview_text

PLAN_SIZE = 7
IDEA_FLAG = "idea"
MAX_LISTED = 50


class IdeasError(Exception):
    """Why ideas can't be generated right now, as an i18n key."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


async def best_recent_texts(session: AsyncSession, user: User, channel: Channel) -> list[str]:
    """Texts of the channel's most engaging posts of the last 30 days, for the AI to take after."""
    now = utcnow()
    pubs = await pubs_repo.published_between(session, user.id, now - timedelta(days=30), now, channel_ids=[channel.id])
    texts: list[str] = []
    for pub in sorted(pubs, key=engagement_score, reverse=True):
        post = await session.get(Post, pub.post_id)
        text = part_preview_text(post.parts[0]).strip() if post and post.parts else ""
        if text and text not in texts:
            texts.append(text[:700])
        if len(texts) >= 8:
            break
    return texts


async def can_generate(session: AsyncSession, settings: Settings, channel: Channel) -> bool:
    """AI ideas come with the channel's paid plan or trial."""
    owner = await session.get(User, channel.owner_id)
    return owner is not None and entitlements.has_extras(
        await entitlements.for_channel(session, settings, channel, owner, utcnow())
    )


async def generate(
    session: AsyncSession, settings: Settings, ai: AIService | None, user: User, channel: Channel,
) -> list[str]:
    """Ask the AI for a week of drafts, charging the channel one AI text (refunded if the request fails).

    Commits before the long request, so two taps can't both spend the channel's last AI text."""
    if ai is None or not ai.enabled:
        raise IdeasError("ai.disabled")
    if not await can_generate(session, settings, channel):
        raise IdeasError("paywall.extras_short")
    if await analytics.count_since(session, user.id, "ai_call", utcnow() - timedelta(days=1)) >= settings.ai_daily_limit_paid:
        raise IdeasError("ai.quota_over")
    if not await limits.take(session, channel.id, "ai_text"):
        raise IdeasError("ai.quota_channel_over")
    await session.commit()
    try:
        ideas = await ai.content_plan(
            channel_title=channel.title, style=channel.ai_style_prompt,
            examples=await best_recent_texts(session, user, channel), lang=user.lang, count=PLAN_SIZE,
        )
    except AIError as e:
        await limits.add(session, channel.id, "ai_text", 1)
        raise IdeasError(e.key) from e
    analytics.track(session, user.id, "ai_call", action="plan")
    return ideas


async def save(session: AsyncSession, channel: Channel, texts: list[str]) -> list[Post]:
    """Keep generated drafts as idea posts of the channel, ready to be scheduled."""
    options = {**initial_options(channel, False), IDEA_FLAG: True}
    buttons = channel_defaults(channel)["buttons"]
    return [
        await posts_repo.create_post(session, channel.owner_id, [channel.id], options=options, text=text, buttons=buttons)
        for text in texts
    ]


def is_idea(post: Post) -> bool:
    return post.status == "draft" and bool((post.options or {}).get(IDEA_FLAG))


def can_keep(post: Post) -> bool:
    """A draft for exactly one channel can be parked in that channel's ideas."""
    return post.status == "draft" and len(post.targets) == 1


async def keep(session: AsyncSession, post: Post) -> None:
    """Park a draft (anything the owner sent the bot) among its channel's ideas, to be scheduled later."""
    post.options = {**(post.options or {}), IDEA_FLAG: True}
    await session.flush()


async def for_channel(session: AsyncSession, channel: Channel) -> list[Post]:
    """The channel's unscheduled ideas, newest first."""
    stmt = (
        select(Post)
        .where(
            Post.owner_id == channel.owner_id,
            Post.status == "draft",
            Post.id.in_(select(PostTarget.post_id).where(PostTarget.channel_id == channel.id)),
        )
        .order_by(Post.created_at.desc(), Post.id.desc())
        .limit(MAX_LISTED * 4)
    )
    posts = [p for p in (await session.scalars(stmt)).all() if is_idea(p)]
    return posts[:MAX_LISTED]


async def schedule(session: AsyncSession, user: User, post: Post, run_at: datetime) -> None:
    """Turn an idea into an ordinary scheduled post."""
    post.options = {k: v for k, v in (post.options or {}).items() if k != IDEA_FLAG}
    await pubs_repo.cancel_pending(session, post.id)
    await pubs_repo.create_publications(session, post, run_at)
    post.status = "scheduled"
    analytics.track(session, user.id, "post_scheduled", post_id=post.id, source="idea")
    await session.flush()
