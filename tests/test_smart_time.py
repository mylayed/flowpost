from datetime import datetime, timezone

from flowpost.db.models import Post, PostTarget, Publication
from flowpost.services.smart_time import best_slots


async def _pub(sessionmaker, seeded, published_at: datetime, *, reactions: dict | None = None, comments: int = 0) -> None:
    async with sessionmaker() as session:
        post = Post(owner_id=seeded.user_id)
        post.targets = [PostTarget(channel_id=seeded.channel_id, position=0)]
        session.add(post)
        await session.flush()
        session.add(Publication(
            post_id=post.id, channel_id=seeded.channel_id, owner_id=seeded.user_id, run_at=published_at,
            status="published", published_at=published_at, message_ids={},
            reactions=reactions or {}, comments_count=comments,
        ))
        await session.commit()


async def test_ranks_slot_with_higher_average_engagement_first(sessionmaker, seeded):
    # Two Wednesday 18:00 (Kyiv, UTC+2/3) posts with strong engagement...
    for day in (4, 11):  # both Wednesdays, UTC 16:00 == 18:00 Kyiv (winter offset)
        await _pub(
            sessionmaker, seeded, datetime(2026, 2, day, 16, 0, tzinfo=timezone.utc),
            reactions={"1": {"👍": 20}}, comments=5,
        )
    # ...vs two Friday 09:00 posts with weak engagement.
    for day in (6, 13):
        await _pub(
            sessionmaker, seeded, datetime(2026, 2, day, 7, 0, tzinfo=timezone.utc),
            reactions={"1": {"👍": 1}}, comments=0,
        )
    async with sessionmaker() as session:
        slots = await best_slots(session, seeded.user_id, [seeded.channel_id], "Europe/Kyiv")
    assert slots[0].weekday == 2 and slots[0].hour == 18  # Wednesday
    assert slots[0].avg_score > slots[-1].avg_score


async def test_ignores_slots_with_a_single_sample(sessionmaker, seeded):
    await _pub(sessionmaker, seeded, datetime(2026, 2, 4, 16, 0, tzinfo=timezone.utc), reactions={"1": {"👍": 50}})
    async with sessionmaker() as session:
        slots = await best_slots(session, seeded.user_id, [seeded.channel_id], "Europe/Kyiv")
    assert slots == []
