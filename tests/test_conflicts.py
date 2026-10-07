from datetime import timedelta

from flowpost.db.models import Channel, Post, PostPart, PostTarget, Publication, User
from flowpost.db.types import utcnow
from flowpost.services.conflicts import find_conflicts, warning_text


async def _queue(sessionmaker, seeded, *, text_html: str, at, owner_id=None, is_ad=False, status="pending") -> None:
    async with sessionmaker() as session:
        owner = owner_id or seeded.user_id
        post = Post(owner_id=owner, is_ad=is_ad)
        post.parts = [PostPart(position=0, text_html=text_html, media=[], buttons=[])]
        post.targets = [PostTarget(channel_id=seeded.channel_id, position=0)]
        session.add(post)
        await session.flush()
        session.add(Publication(
            post_id=post.id, channel_id=seeded.channel_id, owner_id=owner, run_at=at, status=status,
            published_at=at if status == "published" else None, message_ids={},
        ))
        await session.commit()


async def _check(sessionmaker, seeded, at):
    async with sessionmaker() as session:
        channel = await session.get(Channel, seeded.channel_id)
        return await find_conflicts(session, [seeded.post_id], [channel], at)


async def test_flags_posts_within_an_hour_either_side(sessionmaker, seeded):
    at = utcnow() + timedelta(days=1)
    await _queue(sessionmaker, seeded, text_html="раніше", at=at - timedelta(minutes=50))
    await _queue(sessionmaker, seeded, text_html="реклама", at=at + timedelta(minutes=60), is_ad=True)
    await _queue(sessionmaker, seeded, text_html="далеко", at=at + timedelta(minutes=61))
    await _queue(sessionmaker, seeded, text_html="скасований", at=at, status="cancelled")
    clashes = await _check(sessionmaker, seeded, at)
    assert [c.post.parts[0].text_html for c in clashes] == ["раніше", "реклама"]
    text = warning_text(clashes, at, "Europe/Kyiv", "uk")
    assert "реклама" in text and "Наше місто" in text


async def test_counts_posts_of_other_admins_and_already_published(sessionmaker, seeded):
    async with sessionmaker() as session:
        admin = User(tg_id=777, lang="uk", trial_ends_at=utcnow())
        session.add(admin)
        await session.commit()
        admin_id = admin.id
    now = utcnow()
    await _queue(sessionmaker, seeded, text_html="від адміна", at=now + timedelta(minutes=20), owner_id=admin_id)
    await _queue(sessionmaker, seeded, text_html="щойно вийшов", at=now - timedelta(minutes=30), status="published")
    clashes = await _check(sessionmaker, seeded, now)
    assert {c.post.parts[0].text_html for c in clashes} == {"від адміна", "щойно вийшов"}


async def test_ignores_the_post_itself(sessionmaker, seeded):
    at = utcnow() + timedelta(hours=3)
    async with sessionmaker() as session:
        session.add(Publication(
            post_id=seeded.post_id, channel_id=seeded.channel_id, owner_id=seeded.user_id, run_at=at,
            status="pending", message_ids={},
        ))
        await session.commit()
    assert await _check(sessionmaker, seeded, at) == []
