from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Channel
from flowpost.db.repo import channel_admins as channel_admins_repo

log = logging.getLogger(__name__)


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
        stmt = stmt.where(Channel.chat_id.not_in(discussion_ids))
    result = list((await session.scalars(stmt.order_by(Channel.created_at, Channel.id))).all())
    # TEMP DEBUG: tracing why a discussion group still shows for its owner but not for a delegated admin.
    all_owned = list((await session.scalars(select(Channel).where(Channel.owner_id == owner_id))).all())
    log.info(
        "list_channels DEBUG owner=%s all=%s result_ids=%s",
        owner_id,
        [(c.id, c.chat_id, c.kind, c.title, c.discussion_chat_id, c.is_active) for c in all_owned],
        [c.id for c in result],
    )
    return result


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
) -> tuple[Channel, bool]:
    channel = await session.scalar(select(Channel).where(Channel.owner_id == owner_id, Channel.chat_id == chat_id))
    created = channel is None
    if channel is None:
        channel = Channel(owner_id=owner_id, chat_id=chat_id, watermark={})
        session.add(channel)
    channel.kind = kind
    channel.title = title or str(chat_id)
    channel.username = username
    channel.is_forum = is_forum
    channel.is_active = True
    await session.flush()
    return channel, created
