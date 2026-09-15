"""Suggest good posting times per channel, based on how past posts performed there."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.repo import publications as pubs_repo
from flowpost.db.types import utcnow
from flowpost.services.delivery import engagement_score
from flowpost.services.slots import tz_of

MIN_SAMPLES = 2  # a (weekday, hour) slot needs at least this many past posts to be trusted
EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


@dataclass
class SlotSuggestion:
    weekday: int  # 0 = Monday
    hour: int
    avg_score: float
    samples: int


async def best_slots(
    session: AsyncSession, owner_id: int, channel_ids: list[int], tz_name: str, *, limit: int = 3
) -> list[SlotSuggestion]:
    """Rank (weekday, hour) slots by the average reactions+comments of posts published at that slot."""
    pubs = await pubs_repo.published_between(session, owner_id, EPOCH, utcnow(), channel_ids)
    zone = tz_of(tz_name)
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for pub in pubs:
        local = pub.published_at.astimezone(zone)
        buckets[(local.weekday(), local.hour)].append(engagement_score(pub))
    ranked = [
        SlotSuggestion(weekday=wd, hour=h, avg_score=sum(scores) / len(scores), samples=len(scores))
        for (wd, h), scores in buckets.items()
        if len(scores) >= MIN_SAMPLES
    ]
    ranked.sort(key=lambda s: s.avg_score, reverse=True)
    return ranked[:limit]
