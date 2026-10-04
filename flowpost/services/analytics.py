from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import UsageEvent


def track(session: AsyncSession, user_id: int, kind: str, **meta) -> UsageEvent:
    event = UsageEvent(user_id=user_id, kind=kind, meta=meta)
    session.add(event)
    return event


async def count_since(session: AsyncSession, user_id: int, kind: str, since: datetime) -> int:
    return int(
        await session.scalar(
            select(func.count(UsageEvent.id)).where(
                UsageEvent.user_id == user_id, UsageEvent.kind == kind, UsageEvent.created_at >= since
            )
        )
        or 0
    )
