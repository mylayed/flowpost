import json
from datetime import timedelta

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from flowpost.bot.handlers.editor import ai_tools
from flowpost.bot.handlers.editor.ai_tools import apply_series, run_check, run_series
from flowpost.config import Settings
from flowpost.db.models import Channel, Post, PostPart, User
from flowpost.db.types import utcnow
from flowpost.services import analytics
from flowpost.services.ai import AIError, AIService
from flowpost.services.article import extract

LONG = "<b>Довга стаття</b>\n" + "Речення про місто й новини. " * 40

REPORT = {
    "issues": [
        {"kind": "error", "quote": "новина дня", "note": "«Новина дня»"},
        {"kind": "surzhyk", "quote": "приймати участь", "note": "брати участь"},
        {"kind": "fact", "quote": "100% людей", "note": "Перевірте джерело цифри"},
    ],
    "too_long": False, "length_note": "", "has_cta": False, "cta_note": "Додайте «Підписуйтесь».",
    "corrected": "<b>Новина</b> дня, виправлена",
}


class _StubAI:
    enabled = True

    def __init__(self, fail: str | None = None):
        self.fail = fail
        self.checked: list[str] = []
        self.split: list[str] = []

    async def check_post(self, text, **kw):
        if self.fail:
            raise AIError(self.fail)
        self.checked.append(text)
        return dict(REPORT)

    async def split_series(self, source, **kw):
        self.split.append(source)
        return ["<b>1/3</b> перший", "<b>2/3</b> другий", "<b>3/3</b> третій"]


def _fsm() -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=1, user_id=1))


def _settings(**kw) -> Settings:
    return Settings(bot_token="1:x", _env_file=None, **kw)


async def _expire_plans(session, seeded) -> None:
    """Free tools must work without a paid plan or trial and without any AI-text quota."""
    user = await session.get(User, seeded.user_id)
    channel = await session.get(Channel, seeded.channel_id)
    user.trial_ends_at = utcnow() - timedelta(days=1)
    channel.trial_ends_at = utcnow() - timedelta(days=1)
    await session.flush()


async def test_check_works_without_plan_and_offers_fix(fake_bot, sessionmaker, seeded):
    async with sessionmaker() as session:
        await _expire_plans(session, seeded)
        user = await session.get(User, seeded.user_id)
        post = await session.get(Post, seeded.post_id)
        state, ai = _fsm(), _StubAI()
        await run_check(fake_bot, 1, session, state, user, ai, _settings(), post, 0)
        await session.commit()
        data = await state.get_data()
    assert ai.checked == ["<b>Новина</b> дня"]
    text = fake_bot.calls[-1][2]
    assert "приймати участь" in text and "Перевірте джерело" in text and "Немає заклику" in text
    assert data["check_fix"] == REPORT["corrected"] and data["check_part"] == 0
    async with sessionmaker() as session:
        assert await analytics.count_since(session, seeded.user_id, "ai_free", utcnow() - timedelta(days=1)) == 1


async def test_check_daily_cap_and_errors(fake_bot, sessionmaker, seeded):
    async with sessionmaker() as session:
        user = await session.get(User, seeded.user_id)
        post = await session.get(Post, seeded.post_id)
        ai = _StubAI()
        await run_check(fake_bot, 1, session, _fsm(), user, ai, _settings(ai_free_daily_limit=0), post, 0)
        assert ai.checked == []
        assert "Ліміт безкоштовних" in fake_bot.calls[-1][2]

        await run_check(fake_bot, 1, session, _fsm(), user, _StubAI(fail="ai.busy"), _settings(), post, 0)
        assert "перевантажений" in fake_bot.calls[-1][2]
        assert await analytics.count_since(session, user.id, "ai_free", utcnow() - timedelta(days=1)) == 0


async def test_series_from_text_and_link(fake_bot, sessionmaker, seeded, monkeypatch):
    async with sessionmaker() as session:
        await _expire_plans(session, seeded)
        user = await session.get(User, seeded.user_id)
        post = await session.get(Post, seeded.post_id)
        state, ai = _fsm(), _StubAI()

        await run_series(fake_bot, 1, session, state, user, ai, _settings(), post, "коротко")
        assert ai.split == [] and "закороткий" in fake_bot.calls[-1][2]

        await run_series(fake_bot, 1, session, state, user, ai, _settings(), post, LONG)
        data = await state.get_data()
        assert ai.split == [LONG] and len(data["series"]) == 3
        assert "Серія з 3 постів" in fake_bot.calls[-1][2]

        async def fake_fetch(url):
            assert url == "https://example.com/a"
            return "Текст статті"

        monkeypatch.setattr(ai_tools, "fetch_text", fake_fetch)
        await run_series(fake_bot, 1, session, state, user, ai, _settings(), post, "example.com/a")
        assert ai.split[-1] == "Текст статті"


def test_apply_series_keeps_media_and_drops_empty_leftovers():
    photo = [{"type": "photo", "file_id": "x"}]
    post = Post(owner_id=1)
    post.parts = [
        PostPart(position=0, text_html="старий", media=photo, buttons=[]),
        PostPart(position=1, text_html="другий", media=[], buttons=[]),
        PostPart(position=2, text_html="третій", media=[], buttons=[]),
        PostPart(position=3, text_html="з відео", media=[{"type": "video", "file_id": "v"}], buttons=[]),
    ]
    apply_series(post, ["a", "b"])
    assert [(p.text_html, bool(p.media), p.position) for p in post.parts] == [("a", True, 0), ("b", False, 1), ("", True, 2)]

    post.parts = [PostPart(position=0, text_html="x", media=[], buttons=[])]
    apply_series(post, ["a", "b", "c"])
    assert [p.text_html for p in post.parts] == ["a", "b", "c"]
    assert [p.position for p in post.parts] == [0, 1, 2]


def test_extract_article_text():
    page = """<html><head><title>Новина &amp; подія</title><script>var x=1;</script></head>
    <body><nav>Меню Головна</nav><article><h1>Заголовок</h1><p>Перший абзац.</p><p>Другий абзац.</p></article>
    <footer>© Сайт</footer></body></html>"""
    text = extract(page)
    assert text.startswith("Новина & подія")
    assert "Перший абзац." in text and "Другий абзац." in text
    assert "Меню" not in text and "var x" not in text and "© Сайт" not in text


async def test_ai_service_parses_check_and_series(monkeypatch):
    service = AIService(_settings(anthropic_api_key="sk-test"))
    seen: list[dict] = []

    async def fake_complete(kwargs):
        seen.append(kwargs)
        if "<source>" in kwargs["messages"][0]["content"][0]["text"]:
            return json.dumps({"posts": ["<b>1</b> a", "<p>2</p> b", ""]})
        return json.dumps({**REPORT, "issues": REPORT["issues"] + [{"kind": "weird", "quote": "q", "note": "n"}]})

    monkeypatch.setattr(service, "_complete", fake_complete)
    report = await service.check_post("<b>Новина</b> дня", lang="uk")
    assert [i["kind"] for i in report["issues"]] == ["error", "surzhyk", "fact"]
    assert seen[0]["output_config"]["format"]["type"] == "json_schema"
    assert "Ukrainian" in seen[0]["messages"][0]["content"][0]["text"]

    posts = await service.split_series(LONG, lang="uk", limit=3000)
    assert posts == ["<b>1</b> a", "2\n\n b"]
