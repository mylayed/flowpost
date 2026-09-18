"""PRO tools: tracked ad links, join requests with a welcome, hidden text, RSS autoposting, the AI content plan,
translation for multiposting and the weekly report — end to end through the real dispatcher."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from flowpost.bot.callbacks import Ed, Nc, Pj, Px
from flowpost.db.models import (
    Channel, Feed, InviteJoin, InviteLink, JoinRequest, MemberCount, Post, Publication, User,
)
from flowpost.db.types import utcnow
from flowpost.services import rss
from flowpost.services.growth import join_settings
from test_bot_flow import BOT_ID, CHANNEL_CHAT, USER_ID, Harness, _post, _seed_published, h  # noqa: F401

READER = 4242
SECOND_CHAT = -1007770001111


def _chat(chat_id: int = CHANNEL_CHAT) -> dict:
    return {"id": chat_id, "type": "channel", "title": "Test Channel"}


def _person(uid: int = READER) -> dict:
    return {"id": uid, "is_bot": False, "first_name": "Марія", "language_code": "uk"}


def _invite(url: str, *, requests: bool = False) -> dict:
    return {"invite_link": url, "creator": {"id": BOT_ID, "is_bot": True, "first_name": "FlowPost"},
            "creates_join_request": requests, "is_primary": False, "is_revoked": False}


async def _connect(h: Harness, chat_id: int = CHANNEL_CHAT) -> int:
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": chat_id}))
    return (await h.db(lambda s: s.scalar(select(Channel).where(Channel.chat_id == chat_id)))).id


async def _member_update(h: Harness, old: str, new: str, url: str | None = None, uid: int = READER) -> None:
    payload = {
        "chat": _chat(), "from": _person(uid), "date": int(datetime.now().timestamp()),
        "old_chat_member": {"status": old, "user": _person(uid)},
        "new_chat_member": {"status": new, "user": _person(uid)},
    }
    if url:
        payload["invite_link"] = _invite(url)
    await h.feed(chat_member=payload)


def _sent(h: Harness, method: str, chat_id: int | None = None) -> list:
    return [m for name, m in h.session.calls if name == method and (chat_id is None or getattr(m, "chat_id", None) == chat_id)]


# ---- menu and paywall ---------------------------------------------------------------------------

async def test_pro_menu_opens_from_the_channel_card_and_is_paywalled_without_a_plan(h: Harness, settings):
    await h.text("/start")
    c = await _connect(h)
    h.session.clear()
    await h.click(Pj(a="ch", c=c))
    card_kb = str(h.session.calls[-1][1].reply_markup)
    assert Px(a="menu", c=c).pack() in card_kb

    await h.click(Px(a="menu", c=c))
    assert "PRO-інструменти" in h.session.texts() and "🔒" not in h.session.texts()

    # trial over and no free plan extras: the tools answer with the paywall
    async def expire(s):
        await s.execute(update(Channel).values(trial_ends_at=utcnow() - timedelta(days=1)))
        await s.execute(update(User).values(trial_ends_at=utcnow() - timedelta(days=1)))
        await s.commit()
    await h.db(expire)
    h.session.clear()
    await h.click(Px(a="links", c=c))
    assert any(n == "AnswerCallbackQuery" and m.show_alert for n, m in h.session.calls)
    assert "платний тариф" in h.session.texts()


# ---- tracked ad links ---------------------------------------------------------------------------

async def test_ad_link_counts_who_came_who_left_and_the_price_per_subscriber(h: Harness):
    await h.text("/start")
    c = await _connect(h)
    await h.click(Px(a="lnk_new", c=c))
    h.session.clear()
    await h.text("Реклама в @kyiv_news")
    created = _sent(h, "CreateChatInviteLink")[0]
    assert created.chat_id == CHANNEL_CHAT and created.name == "Реклама в @kyiv_news"
    link = await h.db(lambda s: s.scalar(select(InviteLink)))
    assert link.url.startswith("https://t.me/+") and "Посилання створено" in h.session.texts()

    # two people come through the link, one of them leaves; a stranger without the link isn't counted
    await _member_update(h, "left", "member", link.url, uid=1)
    await _member_update(h, "left", "member", link.url, uid=2)
    await _member_update(h, "left", "member", None, uid=3)
    await _member_update(h, "member", "left", uid=2)
    joins = list(await h.db(lambda s: s.scalars(select(InviteJoin).order_by(InviteJoin.user_tg_id))))
    assert [(j.user_tg_id, j.left_at is not None) for j in joins] == [(1, False), (2, True)]

    # the ad cost 300 → 150 per subscriber who came
    await h.click(Px(a="lnk_cost", c=c, id=link.id))
    h.session.clear()
    await h.text("300 грн")
    text = h.session.texts()
    assert "Прийшло: 2 · Відписались: 1 · Залишились: 1" in text and "Ціна одного підписника: 150" in text

    h.session.clear()
    await h.click(Px(a="links", c=c))
    assert "прийшло 2, залишилось 1 · 150 за підписника" in h.session.texts()

    await h.click(Px(a="lnk_delok", c=c, id=link.id))
    assert (await h.db(lambda s: s.get(InviteLink, link.id))).revoked
    assert _sent(h, "RevokeChatInviteLink")


# ---- join requests ------------------------------------------------------------------------------

async def test_join_requests_are_welcomed_and_approved_right_away_or_later(h: Harness):
    await h.text("/start")
    c = await _connect(h)
    await h.click(Px(a="join", c=c))
    await h.click(Px(a="jr_ap", c=c))  # off → right away
    await h.click(Px(a="jr_wtext", c=c))
    await h.text("Привіт, {name}! Ласкаво просимо до {title}.")
    await h.click(Px(a="jr_link", c=c))
    channel = await h.db(lambda s: s.get(Channel, c))
    js = join_settings(channel.join_settings)
    assert js["approve"] == "now" and js["welcome"] and js["link"].startswith("https://t.me/+")
    assert _sent(h, "CreateChatInviteLink")[-1].creates_join_request is True

    h.session.clear()
    await h.feed(chat_join_request={
        "chat": _chat(), "from": _person(), "user_chat_id": READER, "date": int(datetime.now().timestamp()),
        "invite_link": _invite(js["link"], requests=True),
    })
    welcome = _sent(h, "SendMessage", READER)[0]
    assert welcome.text == "Привіт, Марія! Ласкаво просимо до Test Channel."
    approved = _sent(h, "ApproveChatJoinRequest")[0]
    assert (approved.chat_id, approved.user_id) == (CHANNEL_CHAT, READER)

    # with a 10-minute delay the worker approves it once the time comes
    await h.click(Px(a="jr_ap", c=c))  # now → 10 min
    h.session.clear()
    await h.feed(chat_join_request={
        "chat": _chat(), "from": _person(READER + 1), "user_chat_id": READER + 1,
        "date": int(datetime.now().timestamp()),
    })
    assert not _sent(h, "ApproveChatJoinRequest")
    row = await h.db(lambda s: s.scalar(select(JoinRequest).where(JoinRequest.user_tg_id == READER + 1)))
    assert row.approve_at > utcnow() + timedelta(minutes=9)
    worker = h.dp.workflow_data["worker"]
    await worker.process_join_approvals(utcnow() + timedelta(minutes=5))
    assert not _sent(h, "ApproveChatJoinRequest")
    await worker.process_join_approvals(utcnow() + timedelta(minutes=11))
    assert _sent(h, "ApproveChatJoinRequest")[0].user_id == READER + 1


# ---- hidden text --------------------------------------------------------------------------------

async def test_hidden_text_is_shown_only_to_subscribers(h: Harness):
    await h.text("/start")
    await _connect(h)
    await h.text("Розіграш! Кодове слово — під кнопкою")
    p = (await _post(h)).id
    await h.click(Ed(a="more", p=p))
    await h.click(Ed(a="mo_hid", p=p))
    await h.text("Кодове слово: СОНЦЕ")
    assert (await _post(h)).options["hidden_text"] == "Кодове слово: СОНЦЕ"

    await h.click(Ed(a="pub", p=p))
    h.session.clear()
    await h.click(Ed(a="pubok", p=p))
    sent = _sent(h, "SendMessage", CHANNEL_CHAT)[0]
    button = sent.reply_markup.inline_keyboard[-1][0]
    assert button.callback_data == f"hx:{p}" and "Показати" in button.text

    async def tap(uid: int) -> str:
        h.session.clear()
        await h.feed(callback_query={
            "id": "hx", "from": _person(uid), "chat_instance": "ch", "data": f"hx:{p}",
            "message": {"message_id": 55, "date": int(datetime.now().timestamp()), "chat": _chat(), "text": "post"},
        })
        return _sent(h, "AnswerCallbackQuery")[0].text

    h.session.member_status[READER] = "left"
    assert "лише підписники" in await tap(READER)
    h.session.member_status[READER] = "member"
    assert await tap(READER) == "Кодове слово: СОНЦЕ"


# ---- RSS ----------------------------------------------------------------------------------------

def _rss(*items: tuple[str, str]) -> bytes:
    body = "".join(
        f"<item><title>{title}</title><link>https://news.example/{guid}</link><guid>{guid}</guid>"
        f"<description>&lt;p&gt;Подробиці про {title}&lt;/p&gt;</description></item>"
        for guid, title in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Новини міста</title>{body}</channel></rss>'.encode()


def test_rss_and_atom_parsing_and_new_items_order():
    feed = rss.parse(_rss(("b", "Друга"), ("a", "Перша")))
    assert feed.title == "Новини міста" and [i.id for i in feed.items] == ["b", "a"]
    assert feed.items[1].summary == "Подробиці про Перша" and feed.items[1].link == "https://news.example/a"

    atom = rss.parse(b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Blog</title><entry><id>x1</id>'
                     b'<title>Hello</title><link href="https://blog.example/x1"/><summary>Hi there</summary></entry></feed>')
    assert atom.title == "Blog" and atom.items[0].link == "https://blog.example/x1"

    # three new items, two per check: the oldest go first, the newest waits for the next check
    items = rss.parse(_rss(("d", "4"), ("c", "3"), ("b", "2"), ("a", "1"))).items
    fresh, seen = rss.new_items(["a"], items, 2)
    assert [i.id for i in fresh] == ["b", "c"] and set(seen) == {"a", "b", "c"}
    fresh, _ = rss.new_items(seen, items, 2)
    assert [i.id for i in fresh] == ["d"]


async def test_rss_refuses_private_addresses():
    for url in ("http://127.0.0.1/feed", "http://localhost/feed", "http://10.0.0.5/x", "http://169.254.169.254/",
                "file:///etc/passwd", "ftp://example.com/feed"):
        try:
            await rss.fetch(url)
        except rss.FeedError as e:
            assert e.key == "rss.err_url"
        else:  # pragma: no cover
            raise AssertionError(url)


async def test_rss_items_become_drafts_to_approve_or_posts_right_away(h: Harness, monkeypatch):
    await h.text("/start")
    c = await _connect(h)
    content = {"data": _rss(("a", "Стара новина"))}

    async def fake_fetch(url):
        return content["data"]
    monkeypatch.setattr(rss, "fetch", fake_fetch)

    await h.click(Px(a="rss_new", c=c))
    h.session.clear()
    await h.text("news.example/feed")
    feed = await h.db(lambda s: s.scalar(select(Feed)))
    assert feed.url == "https://news.example/feed" and feed.title == "Новини міста" and feed.seen == ["a"]
    assert "Джерело додано" in h.session.texts()

    # a new item appears: the owner gets it as a draft to approve (AI is off, so title + summary + link)
    content["data"] = _rss(("b", "Відкрили новий міст"), ("a", "Стара новина"))
    worker = h.dp.workflow_data["worker"]
    h.session.clear()
    await worker.poll_feed(feed.id, utcnow())
    draft = await _post(h)
    assert draft.status == "draft" and "<b>Відкрили новий міст</b>" in draft.parts[0].text_html
    assert 'href="https://news.example/b"' in draft.parts[0].text_html
    offer = _sent(h, "SendMessage", USER_ID)[0]
    assert "Новий матеріал" in offer.text
    assert offer.reply_markup.inline_keyboard[0][0].callback_data == Px(a="rss_pub", id=draft.id).pack()

    # checking again doesn't repeat it; approving publishes it into the channel
    await worker.poll_feed(feed.id, utcnow())
    assert len(list(await h.db(lambda s: s.scalars(select(Post))))) == 1
    h.session.clear()
    await h.click(Px(a="rss_pub", id=draft.id))
    assert _sent(h, "SendMessage", CHANNEL_CHAT)
    assert (await h.db(lambda s: s.get(Post, draft.id))).status == "published"

    # in «publish right away» mode the next item is queued for the channel without asking
    await h.click(Px(a="feed_mode", c=c, id=feed.id))
    content["data"] = _rss(("c", "Ще новина"), ("b", "Відкрили новий міст"), ("a", "Стара новина"))
    h.session.clear()
    await worker.poll_feed(feed.id, utcnow())
    assert not _sent(h, "SendMessage", USER_ID)
    newest = await _post(h)
    pub = await h.db(lambda s: s.scalar(select(Publication).where(Publication.post_id == newest.id)))
    assert newest.status == "scheduled" and pub.status == "pending"


# ---- AI content plan ----------------------------------------------------------------------------

async def test_ai_content_plan_turns_an_idea_into_a_draft(h: Harness):
    await h.text("/start")
    c = await _connect(h)
    ai = h.dp.workflow_data["ai"]
    ai.client = object()
    asked = {}

    async def fake_plan(**kwargs):
        asked.update(kwargs)
        return [f"<b>Ідея {i}</b>\nТекст поста {i}" for i in range(1, 8)]
    ai.content_plan = fake_plan

    h.session.clear()
    await h.click(Px(a="plan", c=c))
    assert asked["channel_title"] == "Test Channel" and asked["count"] == 7
    shown = h.session.calls[-1][1]
    assert "1. Ідея 1" in shown.text and "7. Ідея 7" in shown.text

    await h.click(Px(a="plan_use", c=c, v="2"))
    post = await _post(h)
    assert post.parts[0].text_html == "<b>Ідея 3</b>\nТекст поста 3" and post.channel_ids == [c]
    assert "Пост №3" in h.session.texts()


# ---- translation for multiposting ---------------------------------------------------------------

async def test_multiposted_post_is_translated_for_a_channel_with_its_own_language(h: Harness):
    await h.text("/start")
    c1 = await _connect(h)
    c2 = await _connect(h, SECOND_CHAT)
    await h.click(Px(a="tr_set", c=c2, v="en"))
    assert (await h.db(lambda s: s.get(Channel, c2))).translate_lang == "en"

    ai = h.dp.workflow_data["ai"]
    ai.client = object()
    calls = []

    async def fake_translate(text, lang, *, limit):
        calls.append((text, lang))
        return "The new bridge is open"
    ai.translate = fake_translate
    h.dp.workflow_data["worker"].ai = ai

    await h.text("Відкрили новий міст")
    p = (await _post(h)).id
    await h.click(Nc(c=c1, p=p))  # two channels connected: the post asks which one first
    await h.click(Ed(a="multi", p=p))
    await h.click(Ed(a="mt", p=p, v=str(c2)))
    await h.click(Ed(a="pub", p=p))
    h.session.clear()
    await h.click(Ed(a="pubok", p=p))
    assert _sent(h, "SendMessage", CHANNEL_CHAT)[0].text.startswith("Відкрили новий міст")
    assert _sent(h, "SendMessage", SECOND_CHAT)[0].text.startswith("The new bridge is open")
    assert calls == [("Відкрили новий міст", "en")]

    # publishing it again reuses the translation instead of paying for a new one
    await h.click(Ed(a="pubok", p=p))
    assert len(calls) == 1


# ---- weekly report ------------------------------------------------------------------------------

async def test_weekly_report_goes_out_on_monday_morning_once(h: Harness):
    channel_id, pub_id = await _seed_published(h, message_id=4242)
    monday = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)  # 11:00 in Kyiv

    async def prepare(s):
        await s.execute(update(Channel).values(created_at=monday - timedelta(days=30),
                                               trial_ends_at=monday + timedelta(days=10)))
        pub = await s.get(Publication, pub_id)
        pub.published_at = monday - timedelta(days=2)
        pub.reactions = {"4242": {"👍": 7}}
        pub.comments_count = 3
        s.add_all([MemberCount(channel_id=channel_id, day=(monday - timedelta(days=7)).date(), count=950),
                   MemberCount(channel_id=channel_id, day=monday.date(), count=1000)])
        await s.commit()
    await h.db(prepare)

    worker = h.dp.workflow_data["worker"]
    h.session.clear()
    await worker.weekly_reports(monday - timedelta(days=1))  # Sunday: not yet
    assert not _sent(h, "SendMessage", USER_ID)

    worker._reports_at = None
    await worker.weekly_reports(monday)
    report = _sent(h, "SendMessage", USER_ID)[0]
    assert "Тижневий звіт" in report.text and "Підписників: 1000 (+50)" in report.text
    assert "Постів: 1 · ❤️ реакцій: 7 · 💬 коментарів: 3" in report.text and "Новина дня" in report.text
    assert "Немає запланованих постів" in report.text

    worker._reports_at = None
    h.session.clear()
    await worker.weekly_reports(monday + timedelta(hours=3))
    assert not _sent(h, "SendMessage", USER_ID)

    await h.click(Px(a="rep_off", c=channel_id))
    assert (await h.db(lambda s: s.get(Channel, channel_id))).weekly_report is False
