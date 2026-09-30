from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Post, Publication
from flowpost.db.repo import channel_admins as channel_admins_repo

ACTIVE_STATUSES = ("pending", "publishing", "paused")


async def create_publications(
    session: AsyncSession,
    post: Post,
    run_at: datetime,
    *,
    status: str = "pending",
    notify: bool = True,
) -> list[Publication]:
    pubs = [
        Publication(
            post_id=post.id,
            channel_id=cid,
            owner_id=post.owner_id,
            run_at=run_at,
            status=status,
            attempts=1 if status == "publishing" else 0,
            notify=notify,
            message_ids={},
        )
        for cid in post.channel_ids
    ]
    session.add_all(pubs)
    await session.flush()
    return pubs


async def cancel_pending(session: AsyncSession, post_id: int) -> None:
    await session.execute(
        update(Publication)
        .where(Publication.post_id == post_id, Publication.status.in_(("pending", "paused")))
        .values(status="cancelled")
    )


async def _accessible_condition(session: AsyncSession, owner_id: int):
    """`owner_id`'s own publications, plus those in channels delegated to them for posting."""
    admin_ids = await channel_admins_repo.administered_channel_ids(session, owner_id, perm="posts")
    condition = Publication.owner_id == owner_id
    if admin_ids:
        condition = condition | Publication.channel_id.in_(admin_ids)
    return condition


async def pending_between(
    session: AsyncSession, owner_id: int, start: datetime, end: datetime, channel_ids: list[int] | None = None
) -> list[Publication]:
    stmt = select(Publication).where(
        await _accessible_condition(session, owner_id),
        Publication.status.in_(("pending", "paused")),
        Publication.run_at >= start,
        Publication.run_at < end,
    )
    if channel_ids:
        stmt = stmt.where(Publication.channel_id.in_(channel_ids))
    return list((await session.scalars(stmt.order_by(Publication.run_at))).all())


MOVABLE_STATUSES = ("pending", "paused")


async def calendar_between(
    session: AsyncSession, owner_id: int, start: datetime, end: datetime, channel_ids: list[int]
) -> list[Publication]:
    """Queued publications due in [start, end) and those published in it, for the Mini App calendar."""
    queued = Publication.status.in_(ACTIVE_STATUSES) & (Publication.run_at >= start) & (Publication.run_at < end)
    published = (
        (Publication.status == "published")
        & Publication.deleted.is_(False)
        & (Publication.published_at >= start)
        & (Publication.published_at < end)
    )
    stmt = select(Publication).where(
        await _accessible_condition(session, owner_id),
        Publication.channel_id.in_(channel_ids),
        queued | published,
    )
    return list((await session.scalars(stmt.order_by(Publication.run_at, Publication.id))).all())


async def move_queued(
    session: AsyncSession, owner_id: int, pub_ids: list[int], run_at: datetime, now: datetime
) -> int:
    """Reschedule the given publications that are still waiting to run. A 'pending' one that is already due belongs
    to the worker (it claims due rows under FOR UPDATE), so it is left alone; a 'paused' one keeps its status and
    runs at the new time once its channel is paid for again. Returns how many were moved."""
    result = await session.execute(
        update(Publication)
        .where(
            Publication.id.in_(pub_ids),
            await _accessible_condition(session, owner_id),
            Publication.status.in_(MOVABLE_STATUSES),
            (Publication.status == "paused") | (Publication.run_at > now),
        )
        .values(run_at=run_at)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


async def next_run(session: AsyncSession, post_id: int) -> datetime | None:
    return await session.scalar(
        select(Publication.run_at)
        .where(Publication.post_id == post_id, Publication.status.in_(("pending", "paused")))
        .order_by(Publication.run_at)
        .limit(1)
    )


async def published_between(
    session: AsyncSession, owner_id: int, start: datetime, end: datetime, channel_ids: list[int] | None = None
) -> list[Publication]:
    stmt = select(Publication).where(
        await _accessible_condition(session, owner_id),
        Publication.status == "published",
        Publication.deleted.is_(False),
        Publication.published_at >= start,
        Publication.published_at < end,
    )
    if channel_ids:
        stmt = stmt.where(Publication.channel_id.in_(channel_ids))
    return list((await session.scalars(stmt.order_by(Publication.published_at))).all())


async def published_for_post(session: AsyncSession, post_id: int) -> list[Publication]:
    stmt = (
        select(Publication)
        .where(Publication.post_id == post_id, Publication.status == "published", Publication.deleted.is_(False))
        .order_by(Publication.published_at.desc())
    )
    return list((await session.scalars(stmt)).all())


_FIND_BY_MESSAGE_BATCH = 300


async def find_by_channel_message(
    session: AsyncSession, owner_id: int, channel_ids: list[int], message_id: int
) -> Publication | None:
    """Scan published publications (most recent first) for the one containing `message_id`.

    There's no portable, indexed way to query inside the `message_ids` JSON blob across both
    SQLite and Postgres, so this pages through in batches instead of capping at one page —
    a single fixed LIMIT would silently stop matching reactions on any post older than that cutoff.
    """
    offset = 0
    while True:
        stmt = (
            select(Publication)
            .where(
                Publication.owner_id == owner_id,
                Publication.channel_id.in_(channel_ids),
                Publication.status == "published",
                Publication.deleted.is_(False),
            )
            .order_by(Publication.published_at.desc())
            .limit(_FIND_BY_MESSAGE_BATCH)
            .offset(offset)
        )
        batch = (await session.scalars(stmt)).all()
        for pub in batch:
            if any(message_id in part.get("ids", []) for part in (pub.message_ids or {}).get("parts", [])):
                return pub
        if len(batch) < _FIND_BY_MESSAGE_BATCH:
            return None
        offset += _FIND_BY_MESSAGE_BATCH


async def refresh_post_status(session: AsyncSession, post: Post) -> None:
    statuses = set((await session.scalars(select(Publication.status).where(Publication.post_id == post.id))).all())
    if statuses & set(ACTIVE_STATUSES):
        post.status = "scheduled"
    elif "published" in statuses:
        post.status = "published"
    elif statuses & {"failed", "missed"}:
        post.status = "failed"
    else:
        post.status = "draft"
