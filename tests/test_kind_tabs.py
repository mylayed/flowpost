from __future__ import annotations

from flowpost.bot.handlers.create_post import channel_picker
from flowpost.bot.handlers.projects import projects_view
from flowpost.db.models import Channel, Post, User


def _labels(kb) -> list[str]:
    return [b.text for row in kb.inline_keyboard for b in row]


async def test_channels_and_groups_are_separate_tabs(sessionmaker, seeded):
    async with sessionmaker() as session:
        user = await session.get(User, seeded.user_id)
        # one kind only: a plain list, no switch
        _, kb = await projects_view(session, user)
        assert not any("Групи" in x for x in _labels(kb))

        session.add(Channel(owner_id=user.id, chat_id=-1009, kind="group", title="Чат міста", watermark={}))
        post = Post(owner_id=user.id)
        session.add(post)
        await session.flush()

        _, kb = await projects_view(session, user)
        labels = _labels(kb)
        assert labels[:2] == ["• 📢 Канали", "👥 Групи"]
        assert any("Наше місто" in x for x in labels) and not any("Чат міста" in x for x in labels)
        _, kb = await projects_view(session, user, "g")
        labels = _labels(kb)
        assert labels[:2] == ["📢 Канали", "• 👥 Групи"]
        assert any("Чат міста" in x for x in labels) and not any("Наше місто" in x for x in labels)

        _, kb = await channel_picker(session, user, post.id, kind="g")
        labels = _labels(kb)
        assert labels[1] == "• 👥 Групи" and "👥 Чат міста" in labels and "📢 Наше місто" not in labels
