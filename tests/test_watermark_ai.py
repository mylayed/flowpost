import io

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from PIL import Image

from flowpost.bot.handlers.editor.ai import run_ai
from flowpost.config import Settings
from flowpost.db.models import Channel, Post, User
from flowpost.services.ai import AIService
from flowpost.services.billing import limits
from flowpost.services.watermark import position_xy, render_photo, wm_cache_key, wm_configured


def _jpeg(w=800, h=600) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (20, 120, 200)).save(buf, "JPEG")
    return buf.getvalue()


def test_render_text_watermark_changes_corner_only():
    settings = {"type": "text", "text": "Наше місто", "position": "br", "opacity": 80, "scale": 30}
    out = Image.open(io.BytesIO(render_photo(_jpeg(), settings, None, None)))
    assert out.size == (800, 600)
    assert out.getpixel((10, 10)) == Image.open(io.BytesIO(_jpeg())).getpixel((10, 10))


def test_render_image_watermark():
    logo = io.BytesIO()
    Image.new("RGBA", (100, 50), (255, 255, 255, 255)).save(logo, "PNG")
    settings = {"type": "image", "image_file_id": "x", "position": "mc", "opacity": 50, "scale": 20}
    out = Image.open(io.BytesIO(render_photo(_jpeg(), settings, logo.getvalue(), None)))
    center = out.getpixel((400, 300))
    assert center != (20, 120, 200)


def test_positions_and_cache_key():
    assert position_xy((1000, 500), (100, 50), "tl") == (15, 15)
    assert position_xy((1000, 500), (100, 50), "br") == (885, 435)
    assert position_xy((1000, 500), (100, 50), "mc") == (450, 225)
    assert wm_cache_key(1, {"text": "a"}) != wm_cache_key(1, {"text": "b"})
    assert not wm_configured({}) and wm_configured({"text": "x"})


def test_ai_request_shape():
    service = AIService(Settings(bot_token="1:x", anthropic_api_key="sk-test", _env_file=None))
    assert service.enabled
    req = service._build_request("screenshot", text="чернетка", lang="uk", limit=1000, style="Коротко",
                                 instruction=None, image=(b"img", "image/jpeg"))
    assert req["model"] == "claude-opus-5"
    assert req["fallbacks"] == "default" and req["betas"] == ["server-side-fallback-2026-07-01"]
    assert req["output_config"] == {"effort": "medium"}
    content = req["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[1]["type"] == "text"
    assert "Коротко" in req["system"][1]["text"]
    assert "thinking" not in req and "temperature" not in req


def test_ai_disabled_without_key():
    assert not AIService(Settings(bot_token="1:x", _env_file=None)).enabled


class _StubAI:
    enabled = True
    calls = 0

    async def generate(self, action, **kw):
        _StubAI.calls += 1
        return "generated text"


async def _fsm(fake_bot) -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=1, user_id=1))


async def test_ai_generation_blocked_and_spent_by_channel_quota(fake_bot, sessionmaker, seeded):
    settings = Settings(bot_token="1:x", ai_daily_limit_trial=100, _env_file=None)
    async with sessionmaker() as session:
        user = await session.get(User, seeded.user_id)
        post = await session.get(Post, seeded.post_id)
        channel = await session.get(Channel, seeded.channel_id)
        channel.title = "Channel"
        state = await _fsm(fake_bot)
        ai = _StubAI()

        # No ai_text quota granted yet -> blocked, nothing generated.
        await run_ai(fake_bot, 1, session, state, user, ai, settings, None, post, 0, "format")
        await session.commit()
    assert _StubAI.calls == 0
    assert "AI-текстів" in fake_bot.calls[-1][2]

    async with sessionmaker() as session:
        await limits.add(session, seeded.channel_id, "ai_text", 1)
        await session.commit()

    async with sessionmaker() as session:
        user = await session.get(User, seeded.user_id)
        post = await session.get(Post, seeded.post_id)
        state = await _fsm(fake_bot)
        ai = _StubAI()
        await run_ai(fake_bot, 1, session, state, user, ai, settings, None, post, 0, "format")
        await session.commit()
    assert _StubAI.calls == 1
    async with sessionmaker() as session:
        assert (await limits.remaining(session, seeded.channel_id))["ai_text"] == 0

    # Quota exhausted again after the single generation -> blocked once more.
    async with sessionmaker() as session:
        user = await session.get(User, seeded.user_id)
        post = await session.get(Post, seeded.post_id)
        state = await _fsm(fake_bot)
        ai = _StubAI()
        await run_ai(fake_bot, 1, session, state, user, ai, settings, None, post, 0, "format")
        await session.commit()
    assert _StubAI.calls == 1


def test_item_watermark_overrides_post_setting():
    from flowpost.services.watermark import item_wm

    channel_wm = {"type": "text", "text": "@chan", "position": "tl"}
    photo = {"type": "photo", "file_id": "a"}
    assert item_wm(photo, True, channel_wm)["text"] == "@chan"
    assert item_wm(photo, False, channel_wm) is None
    assert item_wm({**photo, "wm_mode": "on"}, False, channel_wm)["text"] == "@chan"
    assert item_wm({**photo, "wm_mode": "off"}, True, channel_wm) is None
    own = item_wm({**photo, "wm_custom": {"type": "text", "text": "моє"}}, True, channel_wm)
    assert own["text"] == "моє" and own["position"] == "tl"
    assert wm_cache_key(1, own) != wm_cache_key(1, channel_wm)
    # nothing to draw: no channel watermark and no own one
    assert item_wm({**photo, "wm_mode": "on"}, True, {}) is None
