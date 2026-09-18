from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Channel, UsageEvent, User
from flowpost.db.repo import channel_admins as channel_admins_repo
from flowpost.db.types import utcnow


async def list_channels(
    session: AsyncSession, owner_id: int, active_only: bool = True, *,
    perm: str | None = None, exclude_discussion_groups: bool = True,
) -> list[Channel]:
    """Channels `owner_id` owns, plus (if `perm`) channels delegated to them with that admin permission.

    A group linked to some channel purely as its comments/discussion group (`Channel.discussion_chat_id`)
    isn't itself a postable project, so it's excluded by default.
    """
    condition = Channel.owner_id == owner_id
    if perm:
        admin_ids = await channel_admins_repo.administered_channel_ids(session, owner_id, perm=perm)
        if admin_ids:
            condition = condition | Channel.id.in_(admin_ids)
    stmt = select(Channel).where(condition)
    if active_only:
        stmt = stmt.where(Channel.is_active.is_(True))
    if exclude_discussion_groups:
        discussion_ids = select(Channel.discussion_chat_id).where(Channel.discussion_chat_id.is_not(None))
        # A group's chat_id can drift from what's stored as `discussion_chat_id` (Telegram assigns a
        # new one when a basic group migrates to a supergroup) — matching by title too catches the
        # stale duplicate that leaves behind, without needing the link redone.
        discussion_titles = select(Channel.discussion_title).where(
            Channel.owner_id == owner_id, Channel.discussion_title.is_not(None), Channel.discussion_title != "",
        )
        stmt = stmt.where(
            Channel.chat_id.not_in(discussion_ids)
            & ~((Channel.kind == "group") & Channel.title.in_(discussion_titles))
        )
    channels = list((await session.scalars(stmt.order_by(Channel.created_at, Channel.id))).all())
    # Channels the owner pinned in «Інтерфейс → Канали → Порядок каналів» come first, in that order.
    order = await session.scalar(select(User.channel_order).where(User.id == owner_id)) or []
    rank = {channel_id: i for i, channel_id in enumerate(order)}
    channels.sort(key=lambda c: rank.get(c.id, len(rank)))
    return channels


async def get_channel(session: AsyncSession, owner_id: int, channel_id: int) -> Channel | None:
    channel = await session.scalar(select(Channel).where(Channel.id == channel_id))
    if channel is None:
        return None
    if channel.owner_id == owner_id:
        return channel
    if await channel_admins_repo.has_any_access(session, channel_id, owner_id):
        return channel
    return None


async def get_by_ids(session: AsyncSession, owner_id: int, ids: list[int]) -> list[Channel]:
    if not ids:
        return []
    admin_ids = await channel_admins_repo.administered_channel_ids(session, owner_id)
    rows = (await session.scalars(
        select(Channel).where(Channel.id.in_(ids), (Channel.owner_id == owner_id) | (Channel.id.in_(admin_ids)))
    )).all()
    by_id = {c.id: c for c in rows}
    return [by_id[i] for i in ids if i in by_id]


async def channels_by_chat(session: AsyncSession, chat_id: int) -> list[Channel]:
    return list((await session.scalars(select(Channel).where(Channel.chat_id == chat_id))).all())


async def is_discussion_group(session: AsyncSession, chat_id: int) -> bool:
    """Whether `chat_id` is designated (by any owner) as some channel's comments/discussion group."""
    return bool(await session.scalar(select(Channel.id).where(Channel.discussion_chat_id == chat_id).limit(1)))


async def upsert_channel(
    session: AsyncSession,
    owner_id: int,
    *,
    chat_id: int,
    kind: str,
    title: str,
    username: str | None,
    is_forum: bool,
    trial_days: int,
) -> tuple[Channel, bool]:
    """Connect (or reconnect) a chat. `created` is True only the first time this owner ever connects it —
    a chat deleted from «Мої проєкти» and connected again gets its old trial back, not a new one."""
    channel = await session.scalar(select(Channel).where(Channel.owner_id == owner_id, Channel.chat_id == chat_id))
    created = channel is None
    if channel is None:
        # The trial starts on the first connection only; reconnecting the same channel keeps it.
        previous_trial = await _deleted_trial(session, owner_id, chat_id)
        if previous_trial is not None:
            created = False
        channel = Channel(
            owner_id=owner_id, chat_id=chat_id, watermark={},
            trial_ends_at=previous_trial if previous_trial is not None else utcnow() + timedelta(days=trial_days),
        )
        session.add(channel)
    channel.kind = kind
    channel.title = title or str(chat_id)
    channel.username = username
    channel.is_forum = is_forum
    channel.is_active = True
    await session.flush()
    return channel, created


async def _deleted_trial(session: AsyncSession, owner_id: int, chat_id: int) -> datetime | None:
    """Trial end of this owner's earlier, deleted connection of `chat_id`, if there was one."""
    events = await session.scalars(
        select(UsageEvent.meta).where(UsageEvent.user_id == owner_id, UsageEvent.kind == "channel_deleted")
    )
    ends = [
        datetime.fromisoformat(meta["trial_ends_at"]) if meta.get("trial_ends_at") else utcnow()
        for meta in events if meta.get("chat_id") == chat_id
    ]
    return max(ends) if ends else None


async def delete_channel(session: AsyncSession, channel: Channel) -> None:
    """Remove a project from the bot along with its settings, schedule and stats (FK cascades).

    Leaves a `channel_deleted` event behind so reconnecting the same chat doesn't start a fresh trial.
    """
    trial = channel.trial_ends_at
    session.add(UsageEvent(
        user_id=channel.owner_id, kind="channel_deleted",
        meta={"chat_id": channel.chat_id, "trial_ends_at": trial.isoformat() if trial else None},
    ))
    owner = await session.get(User, channel.owner_id)
    if owner is not None and channel.id in (owner.channel_order or []):
        owner.channel_order = [c for c in owner.channel_order if c != channel.id]
    await session.delete(channel)
    await session.flush()
