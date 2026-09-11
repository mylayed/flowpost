from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Channel


async def list_channels(session: AsyncSession, owner_id: int, active_only: bool = True) -> list[Channel]:
    stmt = select(Channel).where(Channel.owner_id == owner_id)
    if active_only:
        stmt = stmt.where(Channel.is_active.is_(True))
    return list((await session.scalars(stmt.order_by(Channel.created_at, Channel.id))).all())


async def get_channel(session: AsyncSession, owner_id: int, channel_id: int) -> Channel | None:
    return await session.scalar(select(Channel).where(Channel.id == channel_id, Channel.owner_id == owner_id))


async def get_by_ids(session: AsyncSession, owner_id: int, ids: list[int]) -> list[Channel]:
    if not ids:
        return []
    rows = (await session.scalars(select(Channel).where(Channel.owner_id == owner_id, Channel.id.in_(ids)))).all()
    by_id = {c.id: c for c in rows}
    return [by_id[i] for i in ids if i in by_id]


async def channels_by_chat(session: AsyncSession, chat_id: int) -> list[Channel]:
    return list((await session.scalars(select(Channel).where(Channel.chat_id == chat_id))).all())


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
