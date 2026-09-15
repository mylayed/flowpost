from datetime import timedelta

from flowpost.db.models import Channel, Post, PostPart, PostTarget, Publication
from flowpost.db.types import utcnow
from flowpost.services.duplicates import find_duplicates, warning_lines


async def _publish(sessionmaker, seeded, *, text_html: str, media: list | None = None, days_ago: int = 1) -> None:
    async with sessionmaker() as session:
        post = Post(owner_id=seeded.user_id)
        post.parts = [PostPart(position=0, text_html=text_html, media=media or [], buttons=[])]
        post.targets = [PostTarget(channel_id=seeded.channel_id, position=0)]
        session.add(post)
        await session.flush()
        published_at = utcnow() - timedelta(days=days_ago)
        session.add(Publication(
            post_id=post.id, channel_id=seeded.channel_id, owner_id=seeded.user_id, run_at=published_at,
            status="published", published_at=published_at, message_ids={"parts": [{"ids": [42]}]},
        ))
        await session.commit()


async def test_flags_near_identical_text_in_same_channel(sessionmaker, seeded):
    old_text = "<b>Це наша велика новина</b> про важливу подію в місті сьогодні"
    await _publish(sessionmaker, seeded, text_html=old_text)
    async with sessionmaker() as session:
        post = await session.get(Post, seeded.post_id)
        post.parts[0].text_html = old_text  # identical text, new post
        channel = await session.get(Channel, seeded.channel_id)
        matches = await find_duplicates(session, seeded.user_id, post, {channel.id: channel})
    assert len(matches) == 1 and matches[0].kind == "text"
    lines = warning_lines(matches, "Europe/Kyiv", "uk")
    assert len(lines) == 1 and "Наше місто" in lines[0]


async def test_flags_reused_media_by_file_unique_id(sessionmaker, seeded):
    await _publish(sessionmaker, seeded, text_html="старий підпис", media=[{"type": "photo", "uid": "abc123"}])
    async with sessionmaker() as session:
        post = await session.get(Post, seeded.post_id)
        post.parts[0].text_html = "зовсім інший підпис до фото"
        post.parts[0].media = [{"type": "photo", "uid": "abc123"}]
        channel = await session.get(Channel, seeded.channel_id)
        matches = await find_duplicates(session, seeded.user_id, post, {channel.id: channel})
    assert len(matches) == 1 and matches[0].kind == "media"


async def test_no_match_for_unrelated_text(sessionmaker, seeded):
    await _publish(sessionmaker, seeded, text_html="Щось геть інше і не пов'язане зовсім")
    async with sessionmaker() as session:
        post = await session.get(Post, seeded.post_id)
        post.parts[0].text_html = "Цілком інший текст про інші речі"
        channel = await session.get(Channel, seeded.channel_id)
        matches = await find_duplicates(session, seeded.user_id, post, {channel.id: channel})
    assert matches == []


async def test_ignores_matches_outside_lookback_window(sessionmaker, seeded):
    old_text = "<b>Це наша велика новина</b> про важливу подію в місті сьогодні"
    await _publish(sessionmaker, seeded, text_html=old_text, days_ago=120)
    async with sessionmaker() as session:
        post = await session.get(Post, seeded.post_id)
        post.parts[0].text_html = old_text
        channel = await session.get(Channel, seeded.channel_id)
        matches = await find_duplicates(session, seeded.user_id, post, {channel.id: channel})
    assert matches == []
