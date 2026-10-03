"""PRO AI tools: the channel's voice, ad posts from a brief, niche research and the AI answerer in comments."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update

from flowpost.bot.callbacks import Px
from flowpost.db.models import Channel, ChannelAdmin, Post, PostPart, PostTarget, Publication, User
from flowpost.db.types import utcnow
from flowpost.services import ideas as ideas_service
from flowpost.services import pro_ai
from flowpost.services.billing import limits
from test_bot_flow import DISCUSSION_CHAT, USER_ID, Harness, _seed_published, h  # noqa: F401
from test_pro import _comment, _sent

ADMIN_TG = 7001


async def _pro_channel(h: Harness, *, ai_texts: int = 10, posts: int = 6) -> int:
    """A channel on trial with `posts` published posts and `ai_texts` AI texts, and a fake AI client."""
    channel_id, _ = await _seed_published(h, message_id=4242, discussion_thread_id=9001)

    async def setup(s):
        await s.execute(update(Channel).values(trial_ends_at=utcnow() + timedelta(days=5)))
        owner = await s.scalar(select(User).where(User.tg_id == USER_ID))
        for i in range(posts):
            post = Post(owner_id=owner.id, status="published")
            post.parts = [PostPart(position=0, text_html=f"<b>Пост {i}</b>\nДовгий текст поста номер {i} про наше місто.",
                                   media=[], buttons=[])]
            post.targets = [PostTarget(channel_id=channel_id, position=0)]
            s.add(post)
            await s.flush()
            s.add(Publication(post_id=post.id, channel_id=channel_id, owner_id=owner.id, run_at=utcnow(),
                              status="published", published_at=utcnow() - timedelta(days=i + 1), notify=False,
                              message_ids={"parts": [{"ids": [5000 + i]}]}, comments_count=i))
        await limits.add(s, channel_id, "ai_text", ai_texts)
        await s.commit()
    await h.db(setup)
    h.dp.workflow_data["ai"].client = object()
    return channel_id


async def _ai_texts_left(h: Harness, channel_id: int) -> int:
    return (await h.db(lambda s: limits.remaining(s, channel_id)))["ai_text"]


async def _add_admin(h: Harness, channel_id: int, *, settings: bool = True) -> None:
    await h.text("/start", uid=ADMIN_TG)

    async def add(s):
        admin = await s.scalar(select(User).where(User.tg_id == ADMIN_TG))
        s.add(ChannelAdmin(channel_id=channel_id, user_id=admin.id, can_posts=True, can_settings=settings))
        await s.commit()
    await h.db(add)


# ---- menu and paywall ---------------------------------------------------------------------------

async def test_pro_menu_lists_the_ai_tools_and_they_need_a_paid_plan(h: Harness):
    c = await _pro_channel(h)
    h.session.clear()
    await h.click(Px(a="menu", c=c))
    kb = str(h.session.calls[-1][1].reply_markup)
    for action in ("voice", "adgen", "niche", "ans"):
        assert Px(a=action, c=c).pack() in kb

    async def expire(s):
        await s.execute(update(Channel).values(trial_ends_at=utcnow() - timedelta(days=1)))
        await s.execute(update(User).values(trial_ends_at=utcnow() - timedelta(days=1)))
        await s.commit()
    await h.db(expire)
    for action in ("voice", "adgen", "niche", "ans"):
        h.session.clear()
        await h.click(Px(a=action, c=c))
        assert "платний тариф" in h.session.texts()


# ---- 🎯 voice -------------------------------------------------------------------------------------

async def test_voice_profile_from_the_best_posts_becomes_the_channel_style(h: Harness):
    c = await _pro_channel(h)
    await _add_admin(h, c)
    ai = h.dp.workflow_data["ai"]
    asked = {}

    async def fake_voice(examples, **kw):
        asked.update(examples=examples, **kw)
        return "Пиши коротко, на «ти», з емодзі."
    ai.voice_profile = fake_voice

    h.session.clear()
    await h.click(Px(a="voice_go", c=c), uid=ADMIN_TG)  # an admin with settings rights may use it too
    assert "Пиши коротко" in h.session.texts()
    assert asked["channel_title"] == "Test Channel"
    assert asked["examples"][0].startswith("<b>Пост 5</b>")  # the most commented post first
    assert await _ai_texts_left(h, c) == 9

    h.session.clear()
    await h.click(Px(a="voice_ok", c=c), uid=ADMIN_TG)
    assert (await h.db(lambda s: s.get(Channel, c))).ai_style_prompt == "Пиши коротко, на «ти», з емодзі."


async def test_voice_needs_enough_posts_and_refunds_a_failed_request(h: Harness):
    from flowpost.services.ai import AIError

    c = await _pro_channel(h, posts=2)
    h.session.clear()
    await h.click(Px(a="voice_go", c=c))
    assert "Замало опублікованих постів" in h.session.texts()
    assert await _ai_texts_left(h, c) == 10

    async def add_posts(s):
        owner = await s.scalar(select(User).where(User.tg_id == USER_ID))
        for i in range(5):
            post = Post(owner_id=owner.id, status="published")
            post.parts = [PostPart(position=0, text_html=f"Ще один змістовний пост номер {i} для аналізу стилю.", media=[], buttons=[])]
            post.targets = [PostTarget(channel_id=c, position=0)]
            s.add(post)
            await s.flush()
            s.add(Publication(post_id=post.id, channel_id=c, owner_id=owner.id, run_at=utcnow(), status="published",
                              published_at=utcnow(), notify=False, message_ids={}))
        await s.commit()
    await h.db(add_posts)

    async def failing(*a, **kw):
        raise AIError("ai.busy")
    h.dp.workflow_data["ai"].voice_profile = failing
    h.session.clear()
    await h.click(Px(a="voice_go", c=c))
    assert "перевантажений" in h.session.texts()
    assert await _ai_texts_left(h, c) == 10


# ---- 🤝 ad post -----------------------------------------------------------------------------------

async def test_ad_post_from_a_brief_opens_in_the_editor_labelled_as_an_ad(h: Harness):
    c = await _pro_channel(h)
    ai = h.dp.workflow_data["ai"]
    asked = {}

    async def fake_generate(action, **kw):
        asked.update(action=action, **kw)
        return '<b>Кава, що будить місто</b>\nЗнижка 20% за промокодом MISTO. <a href="https://coffee.example">Замовити</a>'
    ai.generate = fake_generate

    await h.click(Px(a="adgen", c=c))
    h.session.clear()
    await h.text("Кав'ярня Ранок, знижка 20% за промокодом MISTO, сайт https://coffee.example")
    assert asked["action"] == "ad" and "MISTO" in asked["text"]
    assert "Кава, що будить місто" in h.session.texts()
    assert await _ai_texts_left(h, c) == 9

    h.session.clear()
    await h.click(Px(a="ad_use", c=c))
    post = await h.db(lambda s: s.scalar(select(Post).where(Post.is_ad.is_(True))))
    assert post is not None and post.status == "draft" and post.options.get("ad_label") is True
    assert "MISTO" in (await h.db(lambda s: s.scalar(select(PostPart).where(PostPart.post_id == post.id)))).text_html
    assert "позначку «Реклама» увімкнено" in h.session.texts()


# ---- 🔍 niche research ----------------------------------------------------------------------------

PUBLIC_PAGE = """<html><head><meta property="og:title" content="Конкурент &amp; Ко"></head><body>
<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message_text js-message_text" dir="auto">
<b>Топ-5 кав'ярень</b><br/>Список місць, куди варто зайти цього тижня.</div>
<span class="tgme_widget_message_views">12.4K</span></div>
<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message_text js-message_text" dir="auto">ok</div></div>
</body></html>"""


def test_channel_refs_public_page_and_question_detection():
    assert pro_ai.parse_channel_refs("@kyiv_news, https://t.me/s/lviv_today\nt.me/odesa_daily/123 @x @kyiv_news") == [
        "kyiv_news", "lviv_today", "odesa_daily",
    ]
    page = pro_ai.parse_public_page(PUBLIC_PAGE, "rival")
    assert page.title == "Конкурент & Ко"
    assert page.posts == [{"text": "Топ-5 кав'ярень\nСписок місць, куди варто зайти цього тижня.", "views": "12.4K"}]
    assert pro_ai.looks_like_question("Скільки коштує доставка")
    assert pro_ai.looks_like_question("А де ви знаходитесь?")
    assert not pro_ai.looks_like_question("Класний пост, дякую")
    assert pro_ai.comment_link(-1001234, 55, None) == "https://t.me/c/1234/55"


async def test_niche_research_reads_competitors_and_saves_the_ideas(h: Harness, monkeypatch):
    c = await _pro_channel(h)
    fetched = []

    async def fake_fetch(username):
        fetched.append(username)
        if username == "closed_one":
            return None
        return pro_ai.PublicChannel(username, f"Канал {username}", [{"text": "Пост конкурента", "views": "1K"}])
    monkeypatch.setattr(pro_ai, "fetch_public_channel", fake_fetch)
    ai = h.dp.workflow_data["ai"]
    asked = {}

    async def fake_report(**kw):
        asked.update(kw)
        return {"report": "<b>Що пишуть конкуренти</b>\n• добірки", "ideas": ["<b>Ідея А</b>", "<b>Ідея Б</b>"]}
    ai.niche_report = fake_report

    await h.click(Px(a="niche_set", c=c))
    h.session.clear()
    await h.text("@rival_news t.me/closed_one @testchan")  # the channel itself is not its own competitor
    assert (await h.db(lambda s: s.get(Channel, c))).ai_tools["competitors"] == ["rival_news", "closed_one"]
    assert "@rival_news" in h.session.texts()

    h.session.clear()
    await h.click(Px(a="niche_go", c=c))
    assert sorted(fetched) == ["closed_one", "rival_news"]
    assert [x["username"] for x in asked["competitors"]] == ["rival_news"]
    assert asked["own_title"] == "Test Channel" and asked["own_posts"]
    texts = h.session.texts()
    assert "Що пишуть конкуренти" in texts and "Не вдалося прочитати: @closed_one" in texts
    assert await _ai_texts_left(h, c) == 9

    await h.click(Px(a="niche_ideas", c=c))

    async def ideas(s):
        return [p.parts[0].text_html for p in await ideas_service.for_channel(s, await s.get(Channel, c))]
    assert sorted(await h.db(ideas)) == ["<b>Ідея А</b>", "<b>Ідея Б</b>"]


async def test_niche_research_without_readable_channels_spends_nothing(h: Harness, monkeypatch):
    c = await _pro_channel(h)

    async def nothing(username):
        return None
    monkeypatch.setattr(pro_ai, "fetch_public_channel", nothing)
    await h.db(lambda s: _set_tools(s, c, competitors=["hidden_chan"]))
    h.session.clear()
    await h.click(Px(a="niche_go", c=c))
    assert "Не вдалося прочитати жоден канал" in h.session.texts()
    assert await _ai_texts_left(h, c) == 10


async def _set_tools(s, channel_id: int, **values) -> None:
    channel = await s.get(Channel, channel_id)
    channel.ai_tools = {**pro_ai.tools_settings(channel.ai_tools), **values}
    await s.commit()


# ---- 🤖 AI answerer -------------------------------------------------------------------------------

class _FakeAnswerer:
    enabled = True

    def __init__(self):
        self.asked: list[dict] = []

    async def answer_comment(self, comment, **kw):
        self.asked.append({"comment": comment, **kw})
        if "доставка" in comment:
            return "answer", "Доставка безкоштовна від 500 грн."
        if "замовлення" in comment:
            return "escalate", ""
        return "skip", ""


async def test_answerer_needs_a_knowledge_base_then_answers_and_escalates(h: Harness):
    c = await _pro_channel(h, ai_texts=2)
    await _add_admin(h, c, settings=False)
    worker = h.dp.workflow_data["worker"]
    worker.ai = fake = _FakeAnswerer()

    h.session.clear()
    await h.click(Px(a="ans_t", c=c))
    assert "Спершу заповніть базу знань" in h.session.texts()

    await h.click(Px(a="ans_kb", c=c))
    await h.text("Доставка безкоштовна від 500 грн. Працюємо щодня з 9 до 21.")
    await h.click(Px(a="ans_t", c=c))
    tools = (await h.db(lambda s: s.get(Channel, c))).ai_tools
    assert tools["answer"] is True and "Доставка" in tools["kb"]

    await _comment(h, 501, "Оля", text="Класний пост")  # not a question: never reaches the AI
    await _comment(h, 502, "Петро", text="Скільки коштує доставка?")
    await _comment(h, 503, "Іра", text="Де моє замовлення №12?")
    assert [q.text for q in worker.questions] == ["Скільки коштує доставка?", "Де моє замовлення №12?"]

    h.session.clear()
    await worker.process_questions()
    assert fake.asked[0]["post"] == "Новина дня" and "Доставка" in fake.asked[0]["knowledge"]
    (reply,) = _sent(h, "SendMessage", DISCUSSION_CHAT)
    assert reply.text == "Доставка безкоштовна від 500 грн."
    escalated = [m for m in _sent(h, "SendMessage") if "замовлення №12" in m.text]
    owner_and_admin = {m.chat_id for m in escalated}
    assert owner_and_admin == {USER_ID, ADMIN_TG}
    assert await _ai_texts_left(h, c) == 0

    # out of AI texts: nothing goes to the AI, the owner hears about it once
    await _comment(h, 504, "Ян", text="Як вас знайти?")
    await _comment(h, 505, "Ян", text="Коли відкриваєтесь?")
    h.session.clear()
    await worker.process_questions()
    assert len(fake.asked) == 2
    (notice,) = _sent(h, "SendMessage", USER_ID)
    assert "на паузі" in notice.text
    assert (await h.db(lambda s: s.get(Channel, c))).ai_tools["answer_out"] is True


async def test_answerer_stays_quiet_when_turned_off(h: Harness):
    c = await _pro_channel(h)
    await h.db(lambda s: _set_tools(s, c, kb="База знань з цінами й адресами", answer=False))
    worker = h.dp.workflow_data["worker"]
    await _comment(h, 502, "Петро", text="Скільки коштує доставка?")
    assert worker.questions == []


async def test_ai_service_answer_comment_escapes_the_comment(settings):
    import json
    from types import SimpleNamespace

    from flowpost.services.ai import AIService

    sent = {}

    async def create(**kwargs):
        sent.update(kwargs)
        body = {"action": "answer", "reply": "Так, працюємо щодня."}
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(body))])

    ai = AIService(settings)
    ai.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    assert await ai.answer_comment("<b>ви працюєте?</b>", knowledge="Щодня 9–21", post="Пост", channel_title="Кава") == (
        "answer", "Так, працюємо щодня.",
    )
    request = sent["messages"][0]["content"][0]["text"]
    assert "<comment>&lt;b&gt;ви працюєте?&lt;/b&gt;</comment>" in request
    assert sent["output_config"]["format"]["type"] == "json_schema"
