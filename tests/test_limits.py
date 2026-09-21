"""Plan limits end to end: trial terms, post counts, watermark and AI quotas, and what the free plan withholds.

Every limit is checked from both sides — it's allowed while there's something left, and it's refused (with nothing
spent and nothing sent) once it runs out or the plan doesn't include it."""
from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, update

from flowpost.bot.callbacks import Ed, Pj
from flowpost.db.models import (
    Channel, ChannelSubscription, ChatTrial, Post, PostPart, PostTarget, Publication, RepeatRule, User,
)
from flowpost.db.repo import channels as channels_repo
from flowpost.db.types import utcnow
from flowpost.services import analytics
from flowpost.services.ai import AIError
from flowpost.services.billing import channel_subs, entitlements, limits
from flowpost.services.billing.wallet import credit
from flowpost.services.publisher import Publisher
from flowpost.services.watermark import WatermarkSkipped
from flowpost.services.worker import Worker

from test_bot_flow import ADMIN_ID, CHANNEL_CHAT, USER_ID, Harness, _post, h  # noqa: F401 - `h` is a fixture

PHOTO = {"type": "photo", "file_id": "orig-photo"}
VIDEO = {"type": "video", "file_id": "orig-video"}
WM = {"type": "text", "text": "@chan"}


class StubWatermarker:
    def __init__(self):
        self.calls = 0

    async def apply(self, bot, item, settings):
        self.calls += 1
        return b"watermarked", "photo.jpg"


class FakeAI:
    enabled = True

    def __init__(self):
        self.calls = 0
        self.fail = False

    async def generate(self, action, **kw):
        self.calls += 1
        if self.fail:
            raise AIError("ai.error")
        return "Готовий текст"


async def _set(sessionmaker, model, obj_id, **values):
    async with sessionmaker() as session:
        obj = await session.get(model, obj_id)
        for key, value in values.items():
            setattr(obj, key, value)
        await session.commit()


async def _quota(sessionmaker, channel_id) -> dict[str, int]:
    async with sessionmaker() as session:
        return await limits.remaining(session, channel_id)


async def _published(sessionmaker, channel_id, n, when=None):
    async with sessionmaker() as session:
        channel = await session.get(Channel, channel_id)
        post_id = (await session.scalars(select(Post.id).where(Post.owner_id == channel.owner_id))).first()
        at = when or utcnow()
        session.add_all([
            Publication(post_id=post_id, channel_id=channel_id, owner_id=channel.owner_id, run_at=at,
                        status="published", published_at=at, message_ids={})
            for _ in range(n)
        ])
        await session.commit()


async def _due(sessionmaker, seeded, **kw) -> int:
    async with sessionmaker() as session:
        pub = Publication(post_id=seeded.post_id, channel_id=seeded.channel_id, owner_id=seeded.user_id,
                          run_at=utcnow() - timedelta(minutes=1), status="pending", message_ids={}, **kw)
        session.add(pub)
        await session.commit()
        return pub.id


def _expire_trial(sessionmaker, channel_id):
    return _set(sessionmaker, Channel, channel_id, trial_ends_at=utcnow() - timedelta(minutes=1))


# ---- trial terms ---------------------------------------------------------------------------------

def test_trial_defaults(settings):
    assert (settings.trial_days, settings.trial_posts) == (30, 100)
    assert settings.trial_quotas == {"wm_photo": 15, "wm_video": 15, "ai_text": 15}


async def test_connecting_a_channel_grants_the_trial_once(h: Harness):
    await h.text("/start")
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    channel = await h.db(lambda s: s.scalar(select(Channel)))
    assert timedelta(days=29, hours=23) < channel.trial_ends_at - utcnow() <= timedelta(days=30)
    assert await _quota(h.sm, channel.id) == {"wm_photo": 15, "wm_video": 15, "ai_text": 15}

    # spend some, then reconnect: neither the trial nor the quotas start over
    async def spend(s):
        await limits.take(s, channel.id, "wm_photo", 5)
        await s.commit()
    await h.db(spend)
    ends_at = channel.trial_ends_at
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    again = await h.db(lambda s: s.get(Channel, channel.id))
    assert again.trial_ends_at == ends_at
    assert await _quota(h.sm, channel.id) == {"wm_photo": 10, "wm_video": 15, "ai_text": 15}
    assert await h.db(lambda s: s.scalar(select(func.count(Channel.id)))) == 1


async def _chat_trial(sessionmaker) -> ChatTrial:
    async with sessionmaker() as session:
        return await session.scalar(select(ChatTrial).where(ChatTrial.chat_id == CHANNEL_CHAT))


async def _plan(sessionmaker, settings, channel_id) -> tuple[str, int | None]:
    async with sessionmaker() as session:
        channel = await session.get(Channel, channel_id)
        owner = await session.get(User, channel.owner_id)
        now = utcnow()
        ent = await entitlements.for_channel(session, settings, channel, owner, now)
        return ent.plan, await entitlements.posts_left(session, settings, channel, owner, ent, now)


async def test_second_account_cannot_restart_the_chats_trial(h: Harness):
    """The trial belongs to the chat: an admin (or a second account of the owner) connecting the very same
    channel joins the trial that is already running instead of starting a new one with new quotas."""
    other = USER_ID + 7
    await h.text("/start")
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    first = await h.db(lambda s: s.scalar(select(Channel)))

    # the chat is 29 days into its trial when the second account shows up
    async def nearly_over(s):
        trial = await s.scalar(select(ChatTrial).where(ChatTrial.chat_id == CHANNEL_CHAT))
        trial.trial_ends_at = utcnow() + timedelta(days=1)
        (await s.get(Channel, first.id)).trial_ends_at = trial.trial_ends_at
        await s.commit()
        return trial.trial_ends_at
    ends_at = await h.db(nearly_over)

    await h.text("/start", uid=other)
    await h.feed(message=h._message(other, chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    second = await h.db(lambda s: s.scalar(select(Channel).where(Channel.id != first.id)))
    assert second is not None and second.chat_id == CHANNEL_CHAT
    assert second.trial_ends_at == ends_at  # the chat's remaining day, not another 30
    assert await _quota(h.sm, second.id) == {"wm_photo": 0, "wm_video": 0, "ai_text": 0}
    assert await h.db(lambda s: s.scalar(select(func.count(ChatTrial.id)))) == 1


async def test_reconnecting_restores_neither_the_trial_nor_its_posts(h: Harness, settings):
    """Disconnecting takes the project's publications with it, so the trial posts already used are booked
    onto the chat — reconnecting brings back the same trial with the same allowance left."""
    await h.text("/start")
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    channel = await h.db(lambda s: s.scalar(select(Channel)))
    await h.text("Пост")
    await _published(h.sm, channel.id, 98)
    assert await _plan(h.sm, settings, channel.id) == ("trial", 2)
    ends_at = (await _chat_trial(h.sm)).trial_ends_at

    await h.click(Pj(a="off", c=channel.id))
    await h.click(Pj(a="offok", c=channel.id))
    assert await h.db(lambda s: s.scalar(select(func.count(Publication.id)))) == 0
    assert (await _chat_trial(h.sm)).posts_used == 98

    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    again = await h.db(lambda s: s.scalar(select(Channel)))
    assert again.trial_ends_at == ends_at
    assert await _plan(h.sm, settings, again.id) == ("trial", 2)


async def test_admin_can_hand_a_chat_a_new_trial(h: Harness, settings):
    """/trial is the way back for a chat that legitimately needs another go — nothing in the bot itself
    can restart a trial."""
    settings.admin_ids = str(ADMIN_ID)
    await h.text("/start")
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    channel = await h.db(lambda s: s.scalar(select(Channel)))
    await h.text("Пост")
    await _published(h.sm, channel.id, 100)
    assert await _plan(h.sm, settings, channel.id) == ("trial", 0)

    h.session.clear()
    await h.text(f"/trial {CHANNEL_CHAT} 7", uid=ADMIN_ID)
    assert "🎁" in h.session.texts()
    trial = await _chat_trial(h.sm)
    assert trial.posts_used == 0 and timedelta(days=6) < trial.trial_ends_at - utcnow() <= timedelta(days=7)
    assert await _plan(h.sm, settings, channel.id) == ("trial", 100)  # posts from before the reset don't count

    h.session.clear()
    await h.text(f"/trial {CHANNEL_CHAT} 0", uid=ADMIN_ID)
    assert "⛔" in h.session.texts()
    # back on the free plan, with today's 100 posts already over its daily allowance
    assert await _plan(h.sm, settings, channel.id) == ("free", 0)


# ---- post counts ---------------------------------------------------------------------------------

async def test_post_limits_per_plan(sessionmaker, seeded, settings):
    now = utcnow()

    async def state():
        async with sessionmaker() as session:
            channel = await session.get(Channel, seeded.channel_id)
            owner = await session.get(User, seeded.user_id)
            ent = await entitlements.for_channel(session, settings, channel, owner, now)
            return ent.plan, await entitlements.posts_left(session, settings, channel, owner, ent, now)

    # trial: 100 posts for the whole trial, counted from the connection, not per day
    await _set(sessionmaker, Channel, seeded.channel_id, created_at=now - timedelta(days=10))
    await _published(sessionmaker, seeded.channel_id, 60, when=now - timedelta(days=5))
    await _published(sessionmaker, seeded.channel_id, 39)
    assert await state() == ("trial", 1)
    await _published(sessionmaker, seeded.channel_id, 1)
    assert await state() == ("trial", 0)

    # trial over → free plan: 10 a day; yesterday's posts don't count
    await _expire_trial(sessionmaker, seeded.channel_id)
    async with sessionmaker() as session:
        await session.execute(update(Publication).values(published_at=now - timedelta(days=2)))
        await session.commit()
    assert await state() == ("free", 10)
    await _published(sessionmaker, seeded.channel_id, 10)
    assert await state() == ("free", 0)

    # paid plan: its own posts per day
    async with sessionmaker() as session:
        session.add(ChannelSubscription(channel_id=seeded.channel_id, posts_per_day=15, paid_until=now + timedelta(days=1)))
        await session.commit()
    assert await state() == ("paid", 5)


async def test_free_allowance_is_shared_by_all_free_channels(sessionmaker, seeded, settings):
    now = utcnow()
    await _expire_trial(sessionmaker, seeded.channel_id)
    async with sessionmaker() as session:
        second = Channel(owner_id=seeded.user_id, chat_id=-100222, kind="channel", title="Другий", watermark={},
                         trial_ends_at=now - timedelta(days=1))
        session.add(second)
        await session.commit()
        second_id = second.id
    await _published(sessionmaker, seeded.channel_id, 7)
    await _published(sessionmaker, second_id, 3)
    async with sessionmaker() as session:
        owner = await session.get(User, seeded.user_id)
        for cid in (seeded.channel_id, second_id):
            channel = await session.get(Channel, cid)
            ent = await entitlements.for_channel(session, settings, channel, owner, now)
            assert await entitlements.posts_left(session, settings, channel, owner, ent, now) == 0


async def test_worker_holds_back_posts_over_the_limit(fake_bot, sessionmaker, seeded, settings):
    worker = Worker(fake_bot, sessionmaker, Publisher(fake_bot, None), settings)
    await _set(sessionmaker, Channel, seeded.channel_id, created_at=utcnow() - timedelta(days=1))
    await _published(sessionmaker, seeded.channel_id, 99)

    last = await _due(sessionmaker, seeded)
    await worker.tick()
    over = await _due(sessionmaker, seeded)
    await worker.tick()
    async with sessionmaker() as session:
        assert (await session.get(Publication, last)).status == "published"
        held = await session.get(Publication, over)
        assert held.status == "pending" and held.run_at > utcnow() + timedelta(hours=23)
    assert sum(1 for c in fake_bot.calls if c[1] == seeded.chat_id and c[0] == "send_message") == 1

    # no plan at all (trial over, no free plan) → paused, nothing sent; paying for the channel resumes it
    no_free = settings.model_copy(update={"free_posts_per_day": 0})
    await _expire_trial(sessionmaker, seeded.channel_id)
    paused = await _due(sessionmaker, seeded)
    fake_bot.calls.clear()
    await Worker(fake_bot, sessionmaker, Publisher(fake_bot, None), no_free).tick()
    async with sessionmaker() as session:
        assert (await session.get(Publication, paused)).status == "paused"
    assert not any(c[1] == seeded.chat_id for c in fake_bot.calls)

    async with sessionmaker() as session:
        await credit(session, seeded.user_id, 1000, bucket="main", kind="topup", ref="test")
        assert await channel_subs.buy(session, no_free, seeded.user_id, [seeded.channel_id], 1, 30, 75)
        await session.commit()
    async with sessionmaker() as session:
        assert (await session.get(Publication, paused)).status == "pending"
    assert (await _quota(sessionmaker, seeded.channel_id))["wm_photo"] == 30  # the plan's quotas came with it


# ---- the free plan: no repeats, no multiposting, no watermarks, no AI ---------------------------

async def test_free_plan_pauses_repeats_and_multiposts(fake_bot, sessionmaker, seeded, settings):
    worker = Worker(fake_bot, sessionmaker, Publisher(fake_bot, None), settings)
    async with sessionmaker() as session:
        session.add(RepeatRule(post_id=seeded.post_id, interval_minutes=60, remaining_count=None, active=True))
        await session.commit()

    # on the trial a repeat goes out and queues the next one
    first = await _due(sessionmaker, seeded)
    await worker.tick()
    async with sessionmaker() as session:
        assert (await session.get(Publication, first)).status == "published"
        queued = (await session.scalars(select(Publication).where(Publication.status == "pending"))).all()
        assert [p.repeat_index for p in queued] == [1]
        queued_id = queued[0].id
        queued[0].run_at = utcnow() - timedelta(minutes=1)
        await session.commit()

    # trial over: the queued repeat is paused, not sent
    await _expire_trial(sessionmaker, seeded.channel_id)
    fake_bot.calls.clear()
    await worker.tick()
    async with sessionmaker() as session:
        assert (await session.get(Publication, queued_id)).status == "paused"
    assert not any(c[1] == seeded.chat_id for c in fake_bot.calls)

    # a post that still has repeat on goes out once on the free plan, without queueing another
    single = await _due(sessionmaker, seeded)
    await worker.tick()
    async with sessionmaker() as session:
        assert (await session.get(Publication, single)).status == "published"
        assert not (await session.scalars(select(Publication).where(Publication.status == "pending"))).all()

    # a multipost on the free plan is paused
    async with sessionmaker() as session:
        await session.execute(update(RepeatRule).values(active=False))
        other = Channel(owner_id=seeded.user_id, chat_id=-100333, kind="channel", title="Третій", watermark={},
                        trial_ends_at=utcnow() - timedelta(days=1))
        session.add(other)
        await session.flush()
        session.add(PostTarget(post_id=seeded.post_id, channel_id=other.id, position=1))
        await session.commit()
    multi = await _due(sessionmaker, seeded)
    fake_bot.calls.clear()
    await worker.tick()
    async with sessionmaker() as session:
        assert (await session.get(Publication, multi)).status == "paused"
    assert not any(c[1] == seeded.chat_id for c in fake_bot.calls)


async def test_watermark_quota_and_plan(fake_bot, sessionmaker, seeded, settings):
    stub = StubWatermarker()
    publisher = Publisher(fake_bot, stub)
    opts = {"watermark": True}
    await _set(sessionmaker, Channel, seeded.channel_id, watermark=WM)
    async with sessionmaker() as session:
        await limits.add(session, seeded.channel_id, "wm_photo", 15)
        await limits.add(session, seeded.channel_id, "wm_video", 1)
        await session.commit()

    async def resolve(items, **kw):
        async with sessionmaker() as session:
            channel = await session.get(Channel, seeded.channel_id)
            media, warnings = await publisher.resolve_media(items, channel, opts, session, **kw)
            await session.commit()
        return ["wm" if not isinstance(m.media, str) else "orig" for m in media], warnings

    # previews never spend the quota
    for _ in range(20):
        assert await resolve([PHOTO], charge=False) == (["wm"], [])
    assert (await _quota(sessionmaker, seeded.channel_id))["wm_photo"] == 15

    # publishing spends one per photo, 15 photos → 15 watermarks, the 16th goes out as is
    for _ in range(15):
        assert await resolve([PHOTO]) == (["wm"], [])
    assert await resolve([PHOTO]) == (["orig"], ["warn.wm_no_quota"])
    assert (await _quota(sessionmaker, seeded.channel_id))["wm_photo"] == 0
    # …and previews stop showing a watermark the post won't get
    assert await resolve([PHOTO], charge=False) == (["orig"], ["warn.wm_no_quota"])

    # videos have their own quota
    assert await resolve([VIDEO, VIDEO]) == (["wm", "orig"], ["warn.wm_no_quota"])
    assert (await _quota(sessionmaker, seeded.channel_id))["wm_video"] == 0

    # not on the plan (free): nothing is drawn and nothing is spent, per-item overrides included
    async with sessionmaker() as session:
        await limits.add(session, seeded.channel_id, "wm_photo", 5)
        await session.commit()
    calls = stub.calls
    own = {**PHOTO, "wm_mode": "on", "wm_custom": {"type": "text", "text": "моє"}}
    assert await resolve([PHOTO, own], wm_allowed=False) == (["orig", "orig"], ["warn.wm_plan"])
    assert stub.calls == calls and (await _quota(sessionmaker, seeded.channel_id))["wm_photo"] == 5


async def test_album_watermarks_are_rendered_together_and_keep_their_order(fake_bot, sessionmaker, seeded):
    """The items of an album are watermarked concurrently; one that can't be drawn keeps its original file
    and leaves the rest of the album in place."""
    started = 0

    class SlowWatermarker:
        async def apply(self, bot, item, settings):
            nonlocal started
            started += 1
            await asyncio.sleep(0.05)
            if item["file_id"] == "bad":
                raise WatermarkSkipped("warn.wm_too_big")
            return b"watermarked-" + item["file_id"].encode(), "photo.jpg"

    publisher = Publisher(fake_bot, SlowWatermarker())
    await _set(sessionmaker, Channel, seeded.channel_id, watermark=WM)
    items = [{"type": "photo", "file_id": fid} for fid in ("a", "b", "bad", "d")]
    async with sessionmaker() as session:
        await limits.add(session, seeded.channel_id, "wm_photo", 10)
        await session.commit()
        channel = await session.get(Channel, seeded.channel_id)
        start = time.perf_counter()
        media, warnings = await publisher.resolve_media(items, channel, {"watermark": True}, session)
        elapsed = time.perf_counter() - start
        await session.commit()

    assert [m.media if isinstance(m.media, str) else m.media.data for m in media] == [
        b"watermarked-a", b"watermarked-b", "bad", b"watermarked-d"
    ]
    assert warnings == ["warn.wm_too_big"]
    assert started == 4
    # Four 50 ms renders overlap instead of running one after another (the real Watermarker caps how
    # many at once with its own semaphore; this stub has none, so all four go together).
    assert elapsed < 0.15


async def test_deferred_video_watermark_goes_out_as_original_and_is_handed_back(fake_bot, sessionmaker, seeded):
    stub = StubWatermarker()
    publisher = Publisher(fake_bot, stub)
    await _set(sessionmaker, Channel, seeded.channel_id, watermark=WM)
    photo = {**PHOTO, "file_id": "p"}
    async with sessionmaker() as session:
        await limits.add(session, seeded.channel_id, "wm_photo", 5)
        await limits.add(session, seeded.channel_id, "wm_video", 5)
        await session.commit()
        channel = await session.get(Channel, seeded.channel_id)
        deferred: list = []
        media, warnings = await publisher.resolve_media(
            [photo, VIDEO], channel, {"watermark": True}, session, charge=False, defer=deferred,
        )
    # the photo is quick and is watermarked on the spot; the video is left for the caller to render
    assert [isinstance(m.media, str) for m in media] == [False, True]
    assert media[1].media == "orig-video" and warnings == []
    assert stub.calls == 1 and [item for item, _ in deferred] == [VIDEO]
    await publisher.warm_watermarks(deferred)
    assert stub.calls == 2


async def test_watermarker_joins_a_render_in_flight_and_keeps_the_result(monkeypatch):
    from flowpost.services.watermark import Watermarker

    wm = Watermarker()
    renders = 0

    async def fake_render(bot, item, s):
        nonlocal renders
        renders += 1
        await asyncio.sleep(0.05)
        return b"out", "video.mp4"

    monkeypatch.setattr(wm, "_render", fake_render)
    item = {"type": "video", "file_id": "v"}
    first, second = await asyncio.gather(wm.apply(None, item, WM), wm.apply(None, item, WM))
    assert first == second == (b"out", "video.mp4") and renders == 1
    assert await wm.apply(None, item, WM) == (b"out", "video.mp4") and renders == 1  # kept for the next preview
    assert await wm.apply(None, item, {**WM, "text": "other"}) == (b"out", "video.mp4") and renders == 2


NEW_CHAT = -1009990001112


def _migrated(fake_bot, *methods):
    """Make the bot's `methods` fail for the old chat id the way Telegram does after a group becomes a supergroup."""
    from aiogram.exceptions import TelegramMigrateToChat
    from aiogram.methods import SendMessage

    for name in methods:
        real = getattr(fake_bot, name)

        async def wrapper(chat_id, *a, _real=real, **kw):
            if chat_id != NEW_CHAT:
                raise TelegramMigrateToChat(SendMessage(chat_id=chat_id, text="x"), "group upgraded", NEW_CHAT)
            return await _real(chat_id, *a, **kw)

        setattr(fake_bot, name, wrapper)


async def test_publishing_into_a_migrated_group_fixes_the_chat_id_and_retries(fake_bot, sessionmaker, seeded, settings):
    _migrated(fake_bot, "send_message")
    async with sessionmaker() as session:
        session.add(ChatTrial(chat_id=seeded.chat_id, trial_ends_at=utcnow() + timedelta(days=5)))
        await session.commit()
    pub_id = await _due(sessionmaker, seeded)
    worker = Worker(fake_bot, sessionmaker, Publisher(fake_bot, None), settings)

    await worker.tick()  # Telegram says the group moved: nothing sent, the id is corrected, the post stays queued
    async with sessionmaker() as session:
        pub = await session.get(Publication, pub_id)
        assert (pub.status, pub.attempts) == ("pending", 0)
        assert (await session.get(Channel, seeded.channel_id)).chat_id == NEW_CHAT
        assert await channels_repo.get_chat_trial(session, NEW_CHAT) is not None  # the trial moved with the chat

    await worker.tick()
    async with sessionmaker() as session:
        assert (await session.get(Publication, pub_id)).status == "published"
    assert any(c[0] == "send_message" and c[1] == NEW_CHAT for c in fake_bot.calls)


async def test_member_count_of_a_migrated_group_is_recorded_under_the_new_id(fake_bot, sessionmaker, seeded, settings):
    _migrated(fake_bot, "get_chat_member_count")
    await Worker(fake_bot, sessionmaker, Publisher(fake_bot, None), settings).snapshot_members(utcnow())
    async with sessionmaker() as session:
        assert (await session.get(Channel, seeded.channel_id)).chat_id == NEW_CHAT


async def test_migrating_a_chat_the_owner_already_connected_under_its_new_id_keeps_one_project(sessionmaker, seeded):
    async with sessionmaker() as session:
        other = Channel(owner_id=seeded.user_id, chat_id=NEW_CHAT, kind="group", title="Супергрупа", watermark={})
        session.add(other)
        await session.commit()
        await channels_repo.migrate_chat(session, seeded.chat_id, NEW_CHAT)
        await session.commit()
        old = await session.get(Channel, seeded.channel_id)
        assert old.chat_id == seeded.chat_id and old.is_active is False  # no second row for (owner, new id)
        assert (await session.get(Channel, other.id)).is_active is True


async def test_worker_publishes_without_watermarks_on_the_free_plan(fake_bot, sessionmaker, seeded, settings):
    stub = StubWatermarker()
    worker = Worker(fake_bot, sessionmaker, Publisher(fake_bot, stub), settings)
    async with sessionmaker() as session:
        post = await session.get(Post, seeded.post_id)
        post.options = {"watermark": True}
        post.parts[0].media = [PHOTO]
        (await session.get(Channel, seeded.channel_id)).watermark = WM
        await limits.add(session, seeded.channel_id, "wm_photo", 3)
        await session.commit()

    await _due(sessionmaker, seeded)
    await worker.tick()
    assert stub.calls == 1 and (await _quota(sessionmaker, seeded.channel_id))["wm_photo"] == 2

    await _expire_trial(sessionmaker, seeded.channel_id)
    free_pub = await _due(sessionmaker, seeded)
    await worker.tick()
    async with sessionmaker() as session:
        pub = await session.get(Publication, free_pub)
        assert pub.status == "published" and pub.message_ids["warnings"] == ["warn.wm_plan"]
    assert stub.calls == 1 and (await _quota(sessionmaker, seeded.channel_id))["wm_photo"] == 2


async def test_extras_allowed(sessionmaker, seeded):
    now = utcnow()
    async with sessionmaker() as session:
        channel = await session.get(Channel, seeded.channel_id)
        assert await entitlements.extras_allowed(session, [channel], now)
        assert not await entitlements.extras_allowed(session, [], now)
        channel.trial_ends_at = now - timedelta(minutes=1)
        assert not await entitlements.extras_allowed(session, [channel], now)
        session.add(ChannelSubscription(channel_id=channel.id, posts_per_day=1, paid_until=now + timedelta(days=1)))
        await session.flush()
        assert await entitlements.extras_allowed(session, [channel], now)
        assert not await entitlements.extras_allowed(session, [channel], now + timedelta(days=2))


# ---- the bot: AI and publishing ------------------------------------------------------------------

async def _ready(h: Harness, fake_ai: FakeAI | None = None) -> tuple[int, int]:
    """/start, connect a channel, write a draft; returns (post id, channel id)."""
    if fake_ai is not None:
        h.dp.workflow_data["ai"] = fake_ai
    await h.text("/start")
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    await h.text("Чернетка новини")
    post = await _post(h)
    return post.id, post.channel_ids[0]


def _alerts(h: Harness) -> list[str]:
    return [m.text for n, m in h.session.calls if n == "AnswerCallbackQuery" and m.show_alert]


async def test_ai_spends_the_channel_quota_and_stops_at_zero(h: Harness):
    ai = FakeAI()
    p, c = await _ready(h, ai)
    assert (await _quota(h.sm, c))["ai_text"] == 15
    for _ in range(15):
        await h.click(Ed(a="ai_run", p=p, v="fix"))
    assert ai.calls == 15 and (await _quota(h.sm, c))["ai_text"] == 0

    h.session.clear()
    await h.click(Ed(a="ai_run", p=p, v="fix"))
    assert ai.calls == 15 and "ліміт" in h.session.texts().lower()

    # a failed request gives the text back
    async def top_up(s):
        await limits.add(s, c, "ai_text", 1)
        await s.commit()
    await h.db(top_up)
    ai.fail = True
    await h.click(Ed(a="ai_run", p=p, v="fix"))
    assert ai.calls == 16 and (await _quota(h.sm, c))["ai_text"] == 1


async def test_ai_daily_limit(h: Harness, settings):
    ai = FakeAI()
    p, c = await _ready(h, ai)
    user = await h.db(lambda s: s.scalar(select(User).where(User.tg_id == USER_ID)))

    async def used_up(s):
        for _ in range(settings.ai_daily_limit_trial):
            analytics.track(s, user.id, "ai_call", action="fix")
        await s.commit()
    await h.db(used_up)
    h.session.clear()
    await h.click(Ed(a="ai_run", p=p, v="fix"))
    assert ai.calls == 0 and (await _quota(h.sm, c))["ai_text"] == 15


async def test_ai_is_not_on_the_free_plan(h: Harness):
    ai = FakeAI()
    p, c = await _ready(h, ai)
    await _expire_trial(h.sm, c)
    h.session.clear()
    await h.click(Ed(a="ai_run", p=p, v="fix"))
    assert ai.calls == 0 and (await _quota(h.sm, c))["ai_text"] == 15
    assert _alerts(h) and "безкоштовний тариф" in _alerts(h)[0]

    # the same for a custom request typed as a message
    await h.click(Ed(a="ai_custom", p=p))
    await h.text("зроби коротше")
    assert ai.calls == 0

    # paying for the channel brings AI back, with the plan's quota
    async def pay(s):
        await credit(s, (await s.scalar(select(User))).id, 1000, bucket="main", kind="topup", ref="test")
        assert await channel_subs.buy(s, SimpleNamespace(posting_plans={1: {"stars": 75, "ai_text": 30}}),
                                      (await s.scalar(select(User))).id, [c], 1, 30, 75)
        await s.commit()
    await h.db(pay)
    await h.click(Ed(a="ai_run", p=p, v="fix"))
    assert ai.calls == 1 and (await _quota(h.sm, c))["ai_text"] == 15 + 30 - 1


async def test_publishing_on_the_free_plan(h: Harness):
    p, c = await _ready(h)
    await _expire_trial(h.sm, c)

    # a plain post into one channel is fine
    await h.click(Ed(a="pub", p=p))
    await h.click(Ed(a="pubok", p=p))
    pubs = await h.db(lambda s: s.scalars(select(Publication)))
    assert [pub.status for pub in pubs.all()] == ["published"]

    # auto-repeat → refused at publish and at schedule, nothing is created
    await h.text("Друга чернетка")
    p2 = (await _post(h)).id
    await h.click(Ed(a="rep", p=p2))
    await h.click(Ed(a="rp_i", p=p2, v="1440"))
    h.session.clear()
    await h.click(Ed(a="pub", p=p2))
    assert _alerts(h) and "безкоштовний тариф" in _alerts(h)[0]
    await h.click(Ed(a="pubok", p=p2))
    tomorrow = (utcnow() + timedelta(days=1)).date().toordinal()
    await h.click(Ed(a="schok", p=p2, v=f"{tomorrow}_1200"))
    count = await h.db(lambda s: s.scalar(select(func.count(Publication.id)).where(Publication.post_id == p2)))
    assert count == 0

    # multiposting → refused too
    await h.click(Ed(a="rp_off", p=p2))

    async def second_channel(s):
        owner = await s.scalar(select(User))
        other = Channel(owner_id=owner.id, chat_id=-100444, kind="channel", title="Ще канал", watermark={},
                        trial_ends_at=utcnow() - timedelta(days=1))
        s.add(other)
        await s.flush()
        s.add(PostTarget(post_id=p2, channel_id=other.id, position=1))
        await s.commit()
    await h.db(second_channel)
    h.session.clear()
    await h.click(Ed(a="pubok", p=p2))
    assert _alerts(h)
    count = await h.db(lambda s: s.scalar(select(func.count(Publication.id)).where(Publication.post_id == p2)))
    assert count == 0


async def test_publishing_without_any_plan_is_refused(h: Harness, settings):
    h.dp.workflow_data["settings"] = settings.model_copy(update={"free_posts_per_day": 0})
    p, c = await _ready(h)
    await _expire_trial(h.sm, c)
    h.session.clear()
    await h.click(Ed(a="pubok", p=p))
    assert _alerts(h) and "пробний період завершився" in _alerts(h)[0]
    assert await h.db(lambda s: s.scalar(select(func.count(Publication.id)))) == 0


async def test_editor_preview_skips_the_watermark_off_plan(h: Harness):
    stub = StubWatermarker()
    h.dp.workflow_data["publisher"] = Publisher(h.bot, stub)
    p, c = await _ready(h)

    async def setup(s):
        post = await s.get(Post, p)
        post.options = {**(post.options or {}), "watermark": True}
        (await s.get(Channel, c)).watermark = WM
        await s.commit()
    await h.db(setup)
    await h.photo()
    assert stub.calls == 1 and (await _quota(h.sm, c))["wm_photo"] == 15  # trial: previewed, not charged

    await _expire_trial(h.sm, c)
    h.session.clear()
    await h.click(Ed(a="home", p=p))
    assert stub.calls == 1
    assert "безкоштовний тариф" in h.session.texts()
