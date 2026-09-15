from __future__ import annotations

import io
import os
from datetime import timedelta
from types import SimpleNamespace

import pytest

os.environ.setdefault("BOT_TOKEN", "123456:TEST")

from flowpost.config import Settings  # noqa: E402
from flowpost.db.base import Base  # noqa: E402
from flowpost.db.models import Channel, Post, PostPart, PostTarget, User  # noqa: E402
from flowpost.db.session import create_engine, create_sessionmaker  # noqa: E402
from flowpost.db.types import utcnow  # noqa: E402


@pytest.fixture
def settings() -> Settings:
    return Settings(
        bot_token="123456:TEST", _env_file=None,
        liqpay_enabled=True, liqpay_public_key="pub", liqpay_private_key="priv",
    )


@pytest.fixture
async def sessionmaker(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield create_sessionmaker(engine)
    await engine.dispose()


class FakeBot:
    """Records Bot API calls and returns minimal message-like objects."""

    def __init__(self):
        self.calls: list[tuple] = []
        self._next_id = 100

    def _msg(self, **extra):
        self._next_id += 1
        return SimpleNamespace(message_id=self._next_id, **extra)

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]

    async def send_message(self, chat_id, text, **kw):
        self.calls.append(("send_message", chat_id, text, kw))
        return self._msg()

    async def send_photo(self, chat_id, photo, **kw):
        self.calls.append(("send_photo", chat_id, photo, kw))
        return self._msg(photo=[SimpleNamespace(file_id=f"photo-{self._next_id + 1}")])

    async def send_video(self, chat_id, video, **kw):
        self.calls.append(("send_video", chat_id, video, kw))
        return self._msg(video=SimpleNamespace(file_id=f"video-{self._next_id + 1}"))

    async def send_animation(self, chat_id, animation, **kw):
        self.calls.append(("send_animation", chat_id, animation, kw))
        return self._msg(animation=SimpleNamespace(file_id=f"anim-{self._next_id + 1}"))

    async def send_document(self, chat_id, document, **kw):
        self.calls.append(("send_document", chat_id, document, kw))
        return self._msg(document=SimpleNamespace(file_id="doc"))

    async def send_audio(self, chat_id, audio, **kw):
        self.calls.append(("send_audio", chat_id, audio, kw))
        return self._msg(audio=SimpleNamespace(file_id="audio"))

    async def send_media_group(self, chat_id, media, **kw):
        self.calls.append(("send_media_group", chat_id, media, kw))
        result = []
        for item in media:
            kind = type(item).__name__.replace("InputMedia", "").lower()
            if kind == "photo":
                result.append(self._msg(photo=[SimpleNamespace(file_id="p")]))
            else:
                result.append(self._msg(**{kind: SimpleNamespace(file_id="x")}))
        return result

    async def send_poll(self, chat_id, question, options, **kw):
        self.calls.append(("send_poll", chat_id, question, {"options": options, **kw}))
        return self._msg(poll=SimpleNamespace(id="poll-1"))

    async def pin_chat_message(self, chat_id, message_id, **kw):
        self.calls.append(("pin_chat_message", chat_id, message_id, kw))
        return True

    async def unpin_chat_message(self, chat_id, message_id=None, **kw):
        self.calls.append(("unpin_chat_message", chat_id, message_id, kw))
        return True

    async def delete_messages(self, chat_id, message_ids, **kw):
        self.calls.append(("delete_messages", chat_id, list(message_ids), kw))
        return True

    async def download(self, file_id, **kw):
        self.calls.append(("download", file_id, kw))
        return io.BytesIO(b"")


@pytest.fixture
def fake_bot() -> FakeBot:
    return FakeBot()


@pytest.fixture
async def seeded(sessionmaker):
    """A user with an active trial, one channel and one text post targeting it."""
    async with sessionmaker() as session:
        user = User(tg_id=555, lang="uk", tz="Europe/Kyiv", trial_ends_at=utcnow() + timedelta(days=7))
        session.add(user)
        await session.flush()
        channel = Channel(owner_id=user.id, chat_id=-1001234567890, kind="channel", title="Наше місто",
                          username="nashe_misto", watermark={})
        session.add(channel)
        await session.flush()
        post = Post(owner_id=user.id, options={"signature": True})
        post.parts = [PostPart(position=0, text_html="<b>Новина</b> дня", media=[], buttons=[])]
        post.targets = [PostTarget(channel_id=channel.id, position=0)]
        post.repeat = None
        session.add(post)
        await session.commit()
        return SimpleNamespace(user_id=user.id, tg_id=user.tg_id, channel_id=channel.id, post_id=post.id,
                               chat_id=channel.chat_id)
