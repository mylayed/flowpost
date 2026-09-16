from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import ChannelFolder, ChannelFolderItem

TITLE_LIMIT = 64


async def list_folders(session: AsyncSession, owner_id: int) -> list[ChannelFolder]:
    stmt = select(ChannelFolder).where(ChannelFolder.owner_id == owner_id)
    return list((await session.scalars(stmt.order_by(ChannelFolder.created_at, ChannelFolder.id))).all())


async def get_folder(session: AsyncSession, owner_id: int, folder_id: int) -> ChannelFolder | None:
    return await session.scalar(
        select(ChannelFolder).where(ChannelFolder.id == folder_id, ChannelFolder.owner_id == owner_id)
    )


async def create_folder(session: AsyncSession, owner_id: int, title: str) -> ChannelFolder:
    folder = ChannelFolder(owner_id=owner_id, title=title[:TITLE_LIMIT])
    session.add(folder)
    await session.flush()
    return folder


async def delete_folder(session: AsyncSession, folder: ChannelFolder) -> None:
    await session.execute(delete(ChannelFolderItem).where(ChannelFolderItem.folder_id == folder.id))
    await session.delete(folder)
    await session.flush()


async def folder_channel_ids(session: AsyncSession, folder_id: int) -> list[int]:
    stmt = select(ChannelFolderItem.channel_id).where(ChannelFolderItem.folder_id == folder_id)
    return list((await session.scalars(stmt.order_by(ChannelFolderItem.id))).all())


async def set_folder_channels(session: AsyncSession, folder_id: int, channel_ids: list[int]) -> None:
    await session.execute(delete(ChannelFolderItem).where(ChannelFolderItem.folder_id == folder_id))
    session.add_all([ChannelFolderItem(folder_id=folder_id, channel_id=c) for c in channel_ids])
    await session.flush()


async def counts_by_folder(session: AsyncSession, owner_id: int) -> dict[int, int]:
    stmt = (
        select(ChannelFolderItem.folder_id, func.count(ChannelFolderItem.id))
        .join(ChannelFolder, ChannelFolder.id == ChannelFolderItem.folder_id)
        .where(ChannelFolder.owner_id == owner_id)
        .group_by(ChannelFolderItem.folder_id)
    )
    return {folder_id: n for folder_id, n in (await session.execute(stmt)).all()}


async def grouped_channel_ids(session: AsyncSession, owner_id: int) -> set[int]:
    """Ids of this owner's channels that already sit in at least one folder."""
    stmt = (
        select(ChannelFolderItem.channel_id)
        .join(ChannelFolder, ChannelFolder.id == ChannelFolderItem.folder_id)
        .where(ChannelFolder.owner_id == owner_id)
    )
    return set((await session.scalars(stmt)).all())
