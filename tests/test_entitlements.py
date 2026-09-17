from datetime import timedelta

from flowpost.db.models import Channel, ChannelSubscription, Publication, Subscription, User
from flowpost.db.types import utcnow
from flowpost.services.billing import entitlements


async def test_channel_plans_and_posts_left(sessionmaker, seeded, settings):
    now = utcnow()
    async with sessionmaker() as session:
        owner = await session.get(User, seeded.user_id)
        channel = await session.get(Channel, seeded.channel_id)
        second = Channel(owner_id=owner.id, chat_id=-100222, kind="channel", title="Другий", watermark={},
                         trial_ends_at=now - timedelta(days=1))
        session.add(second)
        await session.flush()
        for status in ("published", "published", "published", "pending", "failed"):
            session.add(Publication(post_id=seeded.post_id, channel_id=channel.id, owner_id=owner.id, run_at=now,
                                    status=status, published_at=now if status == "published" else None,
                                    message_ids={}))
        await session.flush()

        async def state(ch, cfg=settings):
            ent = await entitlements.for_channel(session, cfg, ch, owner, now)
            return ent.plan, ent.posts_limit, await entitlements.posts_left(session, cfg, ch, owner, ent, now)

        # trial: 100 posts for the whole trial, only published ones count
        assert await state(channel) == ("trial", 100, 97)

        # trial over → free plan: 10 a day per channel, shared by all of the owner's free channels
        channel.trial_ends_at = now - timedelta(minutes=1)
        await session.flush()
        assert await state(channel) == ("free", 10, 7)
        assert await state(second) == ("free", 10, 7)

        # a paid channel counts against its own daily limit and leaves the shared free pool
        session.add(ChannelSubscription(channel_id=channel.id, posts_per_day=15, paid_until=now + timedelta(days=30)))
        await session.flush()
        assert await state(channel) == ("paid", 15, 12)
        assert await state(second) == ("free", 10, 10)

        # an old account-wide subscription keeps the other channels unlimited until it expires
        legacy = Subscription(user_id=owner.id, provider="manual", status="active",
                              current_period_end=now + timedelta(days=5))
        session.add(legacy)
        await session.flush()
        assert await state(second) == ("paid", None, None)

        # without a free plan, a channel with nothing left can't publish at all
        await session.delete(legacy)
        await session.flush()
        assert await state(second, settings.model_copy(update={"free_posts_per_day": 0})) == ("none", 0, 0)
