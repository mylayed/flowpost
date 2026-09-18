from datetime import timedelta
from types import SimpleNamespace

from aiogram.exceptions import TelegramNetworkError
from sqlalchemy import select

from flowpost.db.models import Channel, Post, PostPart, Publication, RepeatRule, User
from flowpost.db.types import utcnow
from flowpost.services.billing import limits
from flowpost.services.publisher import OutMedia, Publisher, SendOptions, send_part
from flowpost.services.worker import Worker


async def test_send_text_with_buttons(fake_bot):
    sent = await send_part(fake_bot, 1, "Hello", [], [[{"text": "Go", "url": "https://t.me/x"}]], SendOptions())
    name, chat, text, kw = fake_bot.calls[0]
    assert name == "send_message" and text == "Hello" and kw["reply_markup"] is not None
    assert sent.text_msg == sent.markup_msg == sent.ids[0]


async def test_send_single_photo_with_caption(fake_bot):
    media = [OutMedia("photo", "file-1", {"type": "photo"})]
    sent = await send_part(fake_bot, 1, "Caption", media, [], SendOptions(silent=True))
    name, _, file_id, kw = fake_bot.calls[0]
    assert name == "send_photo" and file_id == "file-1" and kw["caption"] == "Caption"
    assert kw["disable_notification"] is True
    assert sent.caption_msg == sent.ids[0] and len(fake_bot.calls) == 1


async def test_long_caption_goes_to_separate_message(fake_bot):
    media = [OutMedia("photo", "file-1", {"type": "photo"})]
    sent = await send_part(fake_bot, 1, "x" * 1500, media, [[{"text": "B", "url": "https://t.me/x"}]], SendOptions())
    assert fake_bot.names() == ["send_photo", "send_message"]
    assert fake_bot.calls[0][3]["caption"] is None
    assert sent.markup_msg == sent.text_msg == sent.ids[1]


async def test_album_with_buttons_sends_text_message_after(fake_bot):
    media = [OutMedia("photo", "a", {"type": "photo"}), OutMedia("video", "b", {"type": "video"})]
    sent = await send_part(fake_bot, 1, "Album text", media, [[{"text": "B", "url": "https://t.me/x"}]], SendOptions())
    assert fake_bot.names() == ["send_media_group", "send_message"]
    group = fake_bot.calls[0][2]
    assert group[0].caption is None  # text moved into the buttons message
    assert len(sent.ids) == 3 and sent.markup_msg == sent.ids[2]


async def test_album_without_buttons_keeps_caption(fake_bot):
    media = [OutMedia("photo", "a", {"type": "photo"}), OutMedia("photo", "b", {"type": "photo"})]
    sent = await send_part(fake_bot, 1, "Album text", media, [], SendOptions())
    assert fake_bot.names() == ["send_media_group"]
    assert fake_bot.calls[0][2][0].caption == "Album text"
    assert sent.caption_msg == sent.ids[0]


async def _pub(sessionmaker, seeded, run_at, **kw) -> int:
    async with sessionmaker() as session:
        pub = Publication(post_id=seeded.post_id, channel_id=seeded.channel_id, owner_id=seeded.user_id,
                          run_at=run_at, status="pending", message_ids={}, **kw)
        session.add(pub)
        await session.commit()
        return pub.id


def _worker(fake_bot, sessionmaker, settings) -> Worker:
    return Worker(fake_bot, sessionmaker, Publisher(fake_bot, None), settings)


async def test_worker_publishes_due_post_and_notifies(fake_bot, sessionmaker, seeded, settings):
    async with sessionmaker() as session:
        channel = await session.get(Channel, seeded.channel_id)
        channel.notify_published = True
        await session.commit()
    pub_id = await _pub(sessionmaker, seeded, utcnow() - timedelta(minutes=1))
    await _worker(fake_bot, sessionmaker, settings).tick()
    async with sessionmaker() as session:
        pub = await session.get(Publication, pub_id)
        post = await session.get(Post, seeded.post_id)
        assert pub.status == "published" and pub.message_ids["parts"][0]["ids"]
        assert post.status == "published"
    channel_send = fake_bot.calls[0]
    assert channel_send[0] == "send_message" and channel_send[1] == seeded.chat_id
    assert "https://t.me/nashe_misto" in channel_send[2]  # auto-signature appended
    assert fake_bot.calls[1][1] == seeded.tg_id  # owner notification


async def test_worker_schedules_repeat(fake_bot, sessionmaker, seeded, settings):
    async with sessionmaker() as session:
        session.add(RepeatRule(post_id=seeded.post_id, interval_minutes=60, remaining_count=2, active=True))
        await session.commit()
    run_at = utcnow() - timedelta(minutes=1)
    await _pub(sessionmaker, seeded, run_at)
    await _worker(fake_bot, sessionmaker, settings).tick()
    async with sessionmaker() as session:
        pending = (await session.scalars(select(Publication).where(Publication.status == "pending"))).all()
        assert len(pending) == 1
        assert pending[0].repeat_index == 1
        assert abs((pending[0].run_at - (run_at + timedelta(minutes=60))).total_seconds()) < 2


async def test_worker_pauses_without_access_and_marks_missed(fake_bot, sessionmaker, seeded, settings):
    old_id = await _pub(sessionmaker, seeded, utcnow() - timedelta(hours=5))
    await _worker(fake_bot, sessionmaker, settings).tick()
    async with sessionmaker() as session:
        assert (await session.get(Publication, old_id)).status == "missed"
        channel = await session.get(Channel, seeded.channel_id)
        channel.trial_ends_at = utcnow() - timedelta(days=1)
        await session.commit()
    new_id = await _pub(sessionmaker, seeded, utcnow() - timedelta(minutes=1))
    no_free_plan = settings.model_copy(update={"free_posts_per_day": 0})
    await _worker(fake_bot, sessionmaker, no_free_plan).tick()
    async with sessionmaker() as session:
        assert (await session.get(Publication, new_id)).status == "paused"


async def test_worker_postpones_to_next_day_when_post_limit_is_used_up(fake_bot, sessionmaker, seeded, settings):
    limited = settings.model_copy(update={"trial_posts": 1})
    now = utcnow()
    async with sessionmaker() as session:
        session.add(Publication(post_id=seeded.post_id, channel_id=seeded.channel_id, owner_id=seeded.user_id,
                                run_at=now, status="published", published_at=now, message_ids={}))
        await session.commit()
    run_at = now - timedelta(minutes=1)
    first = await _pub(sessionmaker, seeded, run_at)
    second = await _pub(sessionmaker, seeded, run_at)
    await _worker(fake_bot, sessionmaker, limited).tick()
    async with sessionmaker() as session:
        for pub_id in (first, second):
            pub = await session.get(Publication, pub_id)
            assert pub.status == "pending" and pub.attempts == 0
            assert pub.run_at > utcnow() + timedelta(hours=23)
    # nothing went into the channel (reading its subscriber count for the weekly report isn't posting)
    assert not any(call[1] == seeded.chat_id for call in fake_bot.calls if call[0] != "get_chat_member_count")
    notices = [call for call in fake_bot.calls if call[0] == "send_message" and call[1] == seeded.tg_id]
    assert len(notices) == 1 and "ліміт постів" in notices[0][2]


async def test_pin_and_auto_delete(fake_bot, sessionmaker, seeded, settings):
    async with sessionmaker() as session:
        post = await session.get(Post, seeded.post_id)
        post.options = {**post.options, "pin": True, "pin_hours": 1, "auto_delete_hours": 2}
        await session.commit()
    pub_id = await _pub(sessionmaker, seeded, utcnow() - timedelta(minutes=1))
    worker = _worker(fake_bot, sessionmaker, settings)
    await worker.tick()
    assert "pin_chat_message" in fake_bot.names()
    await worker.tick(utcnow() + timedelta(hours=3))
    assert "unpin_chat_message" in fake_bot.names() and "delete_messages" in fake_bot.names()
    async with sessionmaker() as session:
        pub = await session.get(Publication, pub_id)
        assert pub.deleted and pub.unpin_at is None


async def test_retry_after_mid_post_failure_does_not_resend_earlier_parts(fake_bot, sessionmaker, seeded, settings):
    """A transient failure on part 2 of a 3-part post, then a retry, must not re-send part 1."""
    async with sessionmaker() as session:
        post = await session.get(Post, seeded.post_id)
        post.parts = [
            PostPart(position=0, text_html="Частина 1", media=[], buttons=[]),
            PostPart(position=1, text_html="Частина 2", media=[], buttons=[]),
            PostPart(position=2, text_html="Частина 3", media=[], buttons=[]),
        ]
        await session.commit()
    pub_id = await _pub(sessionmaker, seeded, utcnow() - timedelta(minutes=1))

    class FlakyBot(fake_bot.__class__):
        fail_on_text = "Частина 2"

        async def send_message(self, chat_id, text, **kw):
            if text == self.fail_on_text:
                self.fail_on_text = None  # only fail once
                raise TelegramNetworkError(SimpleNamespace(), "network blip")
            return await super().send_message(chat_id, text, **kw)

    bot = FlakyBot()
    worker = _worker(bot, sessionmaker, settings)
    await worker.tick()
    async with sessionmaker() as session:
        pub = await session.get(Publication, pub_id)
        assert pub.status == "pending"  # rescheduled for retry
        assert len(pub.message_ids["parts"]) == 1  # only part 1 persisted so far

    await worker.tick(utcnow() + timedelta(minutes=5))
    async with sessionmaker() as session:
        pub = await session.get(Publication, pub_id)
        assert pub.status == "published"
        assert len(pub.message_ids["parts"]) == 3

    sent_texts = [c[2] for c in bot.calls if c[0] == "send_message"]
    assert sent_texts.count("Частина 1") == 1
    assert sent_texts.count("Частина 2") == 1
    assert sum(1 for txt in sent_texts if txt.startswith("Частина 3")) == 1  # last part carries the signature


async def test_watermark_cache_reused(fake_bot, sessionmaker, seeded):
    class StubWatermarker:
        calls = 0

        async def apply(self, bot, item, settings):
            StubWatermarker.calls += 1
            return b"jpeg", "photo.jpg"

    publisher = Publisher(fake_bot, StubWatermarker())
    channel = SimpleNamespace(id=1, watermark={"type": "text", "text": "FlowPost"})
    item = {"type": "photo", "file_id": "orig"}
    opts = {"watermark": True}
    media, _ = await publisher.resolve_media([item], channel, opts)
    sent = await send_part(fake_bot, 1, "", media, [], SendOptions())
    assert Publisher.remember_uploads(media, sent)
    media2, _ = await publisher.resolve_media([item], channel, opts)
    assert StubWatermarker.calls == 1 and isinstance(media2[0].media, str)


async def test_watermark_spends_channel_quota(fake_bot, sessionmaker, seeded):
    class StubWatermarker:
        async def apply(self, bot, item, settings):
            return b"jpeg", "photo.jpg"

    publisher = Publisher(fake_bot, StubWatermarker())
    opts = {"watermark": True}
    item = {"type": "photo", "file_id": "orig"}

    async with sessionmaker() as session:
        channel = await session.get(Channel, seeded.channel_id)
        channel.watermark = {"type": "text", "text": "FlowPost"}
        await limits.add(session, seeded.channel_id, "wm_photo", 1)
        await session.commit()

    async with sessionmaker() as session:
        channel = await session.get(Channel, seeded.channel_id)
        media, warnings = await publisher.resolve_media([item], channel, opts, session)
        await session.commit()
    assert not isinstance(media[0].media, str) and warnings == []  # freshly watermarked, no warning

    async with sessionmaker() as session:
        assert (await limits.remaining(session, seeded.channel_id))["wm_photo"] == 0

    async with sessionmaker() as session:
        channel = await session.get(Channel, seeded.channel_id)
        media, warnings = await publisher.resolve_media([item], channel, opts, session)
        await session.commit()
    assert media[0].media == "orig" and warnings == ["warn.wm_no_quota"]  # quota exhausted, published as-is
