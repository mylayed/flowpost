from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import select, update

from flowpost.config import Settings
from flowpost.db.models import (
    BalanceEntry, Channel, ChannelQuota, ChannelSubscription, Payment, Post, Publication, Subscription, User,
)
from flowpost.db.types import utcnow
from flowpost.services.billing import limits, plans
from flowpost.services.billing.stars import parse_payload
from flowpost.services.billing.wallet import apply_topup, cashback_for, credit
from flowpost.web import build_web_app
from flowpost.webapp import api
from flowpost.webapp.auth import validate_init_data

TOKEN = "123456:TEST"


def init_data(user: dict, token: str = TOKEN, auth_date: int | None = None) -> str:
    fields = {"auth_date": str(auth_date or int(time.time())), "query_id": "q1", "user": json.dumps(user)}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class InvoiceBot:
    def __init__(self):
        self.invoices: list[dict] = []
        self.invite_link: str | None = None

    async def get_chat(self, chat_id):
        return SimpleNamespace(username=None, invite_link=self.invite_link)

    async def me(self):
        return SimpleNamespace(username="flowpost_bot")

    async def create_invoice_link(self, **kw):
        self.invoices.append(kw)
        return "https://t.me/$invoice"


async def _client(settings: Settings, sessionmaker, bot) -> TestClient:
    client = TestClient(TestServer(build_web_app(settings, bot, sessionmaker)))
    await client.start_server()
    return client


def test_validate_init_data():
    user = {"id": 42, "first_name": "Олена"}
    assert validate_init_data(init_data(user), TOKEN)["id"] == 42
    assert validate_init_data(init_data(user, token="999:OTHER"), TOKEN) is None
    assert validate_init_data(init_data(user) + "&extra=1", TOKEN) is None
    assert validate_init_data(init_data(user, auth_date=int(time.time()) - 2 * 86400), TOKEN) is None
    assert validate_init_data("", TOKEN) is None
    assert validate_init_data("not-a-query", TOKEN) is None


async def test_webapp_api(sessionmaker):
    settings = Settings(bot_token=TOKEN, webapp_enabled=True, liqpay_enabled=False, _env_file=None)
    bot = InvoiceBot()
    client = await _client(settings, sessionmaker, bot)
    auth = {"Authorization": "tma " + init_data({"id": 555, "first_name": "Олена", "language_code": "uk"})}
    try:
        assert (await client.get("/api/me")).status == 401
        assert (await client.get("/api/me", headers={"Authorization": "tma forged"})).status == 401

        me = await (await client.get("/api/me", headers=auth)).json()
        assert (me["balance"], me["cashback"], me["channels"]) == (0, 0, [])
        assert me["topup"] == {"min": 1, "max": 25000} and me["bot_username"] == "flowpost_bot"
        assert me["legal"] == {"terms_url": "", "privacy_url": "https://telegram.org/privacy-tpa"}
        catalog = me["plans"]
        assert [(p["posts_per_day"], p["stars"]) for p in catalog["posting"]] == [
            (1, 75), (15, 124), (50, 199), (150, 349), (500, 499)
        ]
        assert (catalog["posting"][1]["wm_photo"], catalog["posting"][1]["wm_video"]) == (450, 75)
        assert catalog["term_discounts"] == [[30, 0], [90, 10], [180, 15], [365, 20]]
        assert catalog["channel_discounts"][-1] == [100, 30] and catalog["trial"] == {
                "days": 30, "posts": 100, "quotas": {"wm_photo": 15, "wm_video": 15, "ai_text": 15},
            }
        terms = await (await client.get("/api/terms", headers=auth)).json()
        assert "FlowPost" in terms["html"] and "30" in terms["html"] and "15 фото" in terms["html"]

        assert (await client.post("/api/topup", json={"stars": 0}, headers=auth)).status == 400
        assert (await client.post("/api/topup", json={"stars": "34"}, headers=auth)).status == 400
        resp = await client.post("/api/topup", json={"stars": 34}, headers=auth)
        assert resp.status == 200 and (await resp.json())["link"] == "https://t.me/$invoice"
        async with sessionmaker() as session:
            user = await session.scalar(select(User).where(User.tg_id == 555))
        invoice = bot.invoices[0]
        assert invoice["currency"] == "XTR" and invoice["prices"][0].amount == 34
        assert parse_payload(invoice["payload"]) == (user.id, 34)

        assert (await client.post("/api/lang", json={"lang": "de"}, headers=auth)).status == 400
        assert (await client.post("/api/lang", json={"lang": "en"}, headers=auth)).status == 200
        async with sessionmaker() as session:
            assert (await session.get(User, user.id)).lang == "en"
            other = User(tg_id=999, trial_ends_at=utcnow())
            session.add(other)
            await session.flush()
            mine = Channel(owner_id=user.id, chat_id=-100777, kind="channel", title="Арабаба", watermark={},
                           trial_ends_at=utcnow() + timedelta(days=14))
            foreign = Channel(owner_id=other.id, chat_id=-100888, kind="channel", title="Чужий", watermark={})
            post = Post(owner_id=user.id)
            session.add_all([mine, foreign, post])
            await session.flush()
            session.add_all([
                Publication(post_id=post.id, channel_id=mine.id, owner_id=user.id, run_at=utcnow(), status=status,
                            published_at=utcnow() if status == "published" else None)
                for status in ("published", "published", "pending")
            ])
            channel_id, foreign_id = mine.id, foreign.id
            await session.commit()
        me = await (await client.get("/api/me", headers=auth)).json()
        assert [(c["title"], c["days_left"]) for c in me["channels"]] == [("Арабаба", 14)]
        assert me["renew_soon_days"] == 7 and me["user"]["tz"] == "Europe/Kyiv"

        detail = await (await client.get(f"/api/channels/{channel_id}", headers=auth)).json()
        assert (detail["status"], detail["plan"], detail["days_left"]) == ("active", "trial", 14)
        assert (detail["posts_left"], detail["posts_limit"], detail["posts_window"]) == (98, 100, "trial")
        assert detail["title"] == "Арабаба"
        assert detail["quotas"] == {"wm_photo": 0, "wm_video": 0, "ai_text": 0} and detail["extras"] is True
        assert (await client.get(f"/api/channels/{foreign_id}", headers=auth)).status == 404

        # «Відкрити в Telegram» opens the private channel itself, not t.me/c/<id> (a web page): with no invite
        # link it points at the channel's first message
        assert detail["link"] == "https://t.me/c/777/1"
        api._chat_links.clear()
        bot.invite_link = "https://t.me/+abcDEF"
        detail = await (await client.get(f"/api/channels/{channel_id}", headers=auth)).json()
        assert detail["link"] == "https://t.me/+abcDEF"

        # an account-wide subscription doesn't show while the channel's trial runs…
        async with sessionmaker() as session:
            session.add(Subscription(user_id=user.id, provider="manual", status="active",
                                     current_period_end=utcnow() + timedelta(days=20, hours=1)))
            await session.commit()
        detail = await (await client.get(f"/api/channels/{channel_id}", headers=auth)).json()
        assert (detail["plan"], detail["days_left"], detail["posts_left"], detail["posts_limit"]) == ("trial", 14, 98, 100)

        # …and takes over once the trial ends, as a paid plan of 15 posts a day until its own end date
        async with sessionmaker() as session:
            await session.execute(update(Channel).where(Channel.id == channel_id)
                                  .values(trial_ends_at=utcnow() - timedelta(minutes=1)))
            await session.commit()
        detail = await (await client.get(f"/api/channels/{channel_id}", headers=auth)).json()
        assert (detail["status"], detail["plan"], detail["days_left"]) == ("active", "paid", 21)
        assert (detail["posts_left"], detail["posts_limit"], detail["posts_window"]) == (13, 15, "day")
        assert detail["extras"] is True
        me = await (await client.get("/api/me", headers=auth)).json()
        assert [(c["title"], c["plan"], c["days_left"]) for c in me["channels"]] == [("Арабаба", "paid", 21)]

        # quotas follow what's spent
        async with sessionmaker() as session:
            await limits.add(session, channel_id, "wm_photo", 15)
            await limits.take(session, channel_id, "wm_photo", 4)
            await session.commit()
        detail = await (await client.get(f"/api/channels/{channel_id}", headers=auth)).json()
        assert detail["quotas"]["wm_photo"] == 11

        # subscription over too → free plan: no end date, quotas not included
        async with sessionmaker() as session:
            await session.execute(update(Subscription).values(current_period_end=utcnow() - timedelta(minutes=1)))
            await session.commit()
        detail = await (await client.get(f"/api/channels/{channel_id}", headers=auth)).json()
        assert (detail["plan"], detail["status"], detail["days_left"], detail["extras"]) == ("free", "free", 0, False)
        assert (detail["posts_left"], detail["posts_limit"]) == (8, 10)

        page = await client.get("/app/")
        assert page.status == 200 and "__V__" not in await page.text()
        assert (await client.get("/app/static/app.js")).status == 200
    finally:
        await client.close()


async def test_webapp_can_be_disabled(sessionmaker):
    disabled = Settings(bot_token=TOKEN, webapp_enabled=False, _env_file=None)
    client = await _client(disabled, sessionmaker, InvoiceBot())
    try:
        assert (await client.get("/app/")).status == 404
        assert (await client.get("/api/me")).status == 404
    finally:
        await client.close()


async def test_apply_topup_credits_once_with_cashback(sessionmaker, seeded):
    assert cashback_for(34, 5) == 1 and cashback_for(19, 5) == 0 and cashback_for(1000, 2.5) == 25
    async with sessionmaker() as session:
        assert await apply_topup(session, seeded.user_id, 500, "charge-1", {}, 5) == 25
        assert await apply_topup(session, seeded.user_id, 500, "charge-1", {}, 5) is None
        await session.commit()
    async with sessionmaker() as session:
        user = await session.get(User, seeded.user_id)
        assert (user.balance, user.cashback) == (500, 25)
        entries = (await session.scalars(select(BalanceEntry).order_by(BalanceEntry.id))).all()
        assert [(e.bucket, e.delta, e.kind) for e in entries] == [("main", 500, "topup"), ("cashback", 25, "cashback")]
        assert (await session.scalar(select(Payment))).provider_payment_id == "stars:charge-1"


async def test_buy_limit_packs_from_wallet(sessionmaker, seeded):
    settings = Settings(bot_token=TOKEN, webapp_enabled=True, liqpay_enabled=False, _env_file=None)
    client = await _client(settings, sessionmaker, InvoiceBot())
    auth = {"Authorization": "tma " + init_data({"id": seeded.tg_id, "first_name": "Олена"})}

    async def buy(packs: dict, channel_id: int = seeded.channel_id):
        return await client.post("/api/limits", json={"channel_id": channel_id, "packs": packs}, headers=auth)

    try:
        me = await (await client.get("/api/me", headers=auth)).json()
        assert list(me["limit_prices"]) == ["wm_photo", "wm_video", "ai_text"]
        assert me["limit_prices"]["ai_text"]["500"] == 129
        resp = await client.get(f"/api/limits/{seeded.channel_id}", headers=auth)
        assert (await resp.json())["remaining"] == {"wm_photo": 0, "wm_video": 0, "ai_text": 0}

        for packs in ({}, {"wm_photo": 0}, {"wm_photo": 7}, {"nope": 10}, {"wm_photo": True}):
            assert (await buy(packs)).status == 400, packs
        assert (await buy({"wm_photo": 10}, channel_id=9999)).status == 404

        resp = await buy({"wm_photo": 10, "ai_text": 500})
        assert resp.status == 402 and (await resp.json())["missing"] == 134

        async with sessionmaker() as session:
            await credit(session, seeded.user_id, 100, bucket="main", kind="topup")
            await credit(session, seeded.user_id, 50, bucket="cashback", kind="cashback")
            await session.commit()

        resp = await buy({"wm_photo": 10, "wm_video": 0, "ai_text": 500})
        data = await resp.json()
        assert resp.status == 200 and (data["balance"], data["cashback"]) == (16, 0)
        assert data["remaining"] == {"wm_photo": 10, "wm_video": 0, "ai_text": 500}
        data = await (await buy({"wm_photo": 10})).json()
        assert data["balance"] == 11 and data["remaining"]["wm_photo"] == 20

        # the channel page shows the bought packs on top of what was there
        detail = await (await client.get(f"/api/channels/{seeded.channel_id}", headers=auth)).json()
        assert detail["quotas"] == {"wm_photo": 20, "wm_video": 0, "ai_text": 500}

        async with sessionmaker() as session:
            spends = (await session.scalars(
                select(BalanceEntry).where(BalanceEntry.kind == "spend").order_by(BalanceEntry.id)
            )).all()
            assert [(e.bucket, e.delta) for e in spends] == [("cashback", -50), ("main", -84), ("main", -5)]
    finally:
        await client.close()


async def test_transfer_channel_subscription(sessionmaker, seeded):
    settings = Settings(bot_token=TOKEN, webapp_enabled=True, liqpay_enabled=False, _env_file=None)
    client = await _client(settings, sessionmaker, InvoiceBot())
    auth = {"Authorization": "tma " + init_data({"id": seeded.tg_id, "first_name": "Олена"})}
    now = utcnow()
    source = seeded.channel_id

    async with sessionmaker() as session:
        other = User(tg_id=999, trial_ends_at=now)
        free = Channel(owner_id=seeded.user_id, chat_id=-1002, kind="channel", title="Вільний", watermark={})
        busy = Channel(owner_id=seeded.user_id, chat_id=-1003, kind="channel", title="Зайнятий", watermark={})
        lapsed = Channel(owner_id=seeded.user_id, chat_id=-1004, kind="channel", title="Прострочений", watermark={})
        session.add_all([other, free, busy, lapsed])
        await session.flush()
        foreign = Channel(owner_id=other.id, chat_id=-1005, kind="channel", title="Чужий", watermark={})
        session.add(foreign)
        await session.flush()
        session.add_all([
            ChannelSubscription(channel_id=source, posts_per_day=15, paid_until=now + timedelta(days=20)),
            ChannelSubscription(channel_id=busy.id, posts_per_day=1, paid_until=now + timedelta(days=5)),
            ChannelSubscription(channel_id=lapsed.id, posts_per_day=50, paid_until=now - timedelta(days=1)),
            ChannelQuota(channel_id=source, kind="wm_photo", remaining=10),
            ChannelQuota(channel_id=source, kind="ai_text", remaining=100),
            ChannelQuota(channel_id=lapsed.id, kind="wm_photo", remaining=5),
        ])
        ids = {"free": free.id, "busy": busy.id, "lapsed": lapsed.id, "foreign": foreign.id}
        await session.commit()

    async def move(from_id: int, to_id: int):
        return await client.post("/api/transfer", json={"from_id": from_id, "to_id": to_id}, headers=auth)

    try:
        options = await (await client.get("/api/transfer", headers=auth)).json()
        assert [c["id"] for c in options["sources"]] == [source, ids["busy"]]
        assert [c["id"] for c in options["targets"]] == [ids["free"], ids["lapsed"]]
        assert options["sources"][0]["quotas"] == {"wm_photo": 10, "wm_video": 0, "ai_text": 100}

        assert (await move(source, source)).status == 400
        assert (await move(source, ids["foreign"])).status == 404
        assert (await (await move(source, ids["busy"])).json())["error"] == "target_subscribed"
        assert (await (await move(ids["free"], ids["lapsed"])).json())["error"] == "not_transferable"

        assert (await move(source, ids["lapsed"])).status == 200
        detail = await (await client.get(f"/api/channels/{ids['lapsed']}", headers=auth)).json()
        assert (detail["plan"], detail["posts_per_day"], detail["days_left"]) == ("paid", 15, 20)
        old = await (await client.get(f"/api/channels/{source}", headers=auth)).json()
        assert (old["plan"], old["posts_per_day"]) == ("trial", None)
        assert (await (await client.get(f"/api/limits/{ids['lapsed']}", headers=auth)).json())["remaining"] == {
            "wm_photo": 15, "wm_video": 0, "ai_text": 100,
        }
        async with sessionmaker() as session:
            assert await session.scalar(select(ChannelQuota).where(ChannelQuota.channel_id == source)) is None
            subs = (await session.scalars(select(ChannelSubscription).order_by(ChannelSubscription.channel_id))).all()
            assert [(s.channel_id, s.posts_per_day) for s in subs] == sorted([(ids["busy"], 1), (ids["lapsed"], 15)])
    finally:
        await client.close()


async def test_subscribe_channels_from_wallet(sessionmaker, seeded):
    settings = Settings(bot_token=TOKEN, webapp_enabled=True, liqpay_enabled=False, _env_file=None)
    assert plans.quote(settings, 15, 30, 1) == (124, 30)
    assert plans.quote(settings, 15, 30, 1, round_to_pack=True) == (150, 36)
    assert plans.quote(settings, 15, 90, 1) == (335, 90)
    assert plans.quote(settings, 15, 30, 3) == (365, 30)
    assert plans.quote(settings, 7, 30, 1) is None and plans.quote(settings, 15, 45, 1) is None

    client = await _client(settings, sessionmaker, InvoiceBot())
    auth = {"Authorization": "tma " + init_data({"id": seeded.tg_id, "first_name": "Олена"})}
    async with sessionmaker() as session:
        other = User(tg_id=999, trial_ends_at=utcnow())
        session.add(other)
        await session.flush()
        foreign = Channel(owner_id=other.id, chat_id=-1005, kind="channel", title="Чужий", watermark={})
        session.add(foreign)
        await session.flush()
        foreign_id = foreign.id
        await session.commit()

    async def buy(**overrides):
        body = {"channel_ids": [seeded.channel_id], "posts_per_day": 15, "days": 30, "stars": 124, **overrides}
        return await client.post("/api/subscribe", json=body, headers=auth)

    try:
        me = await (await client.get("/api/me", headers=auth)).json()
        assert me["plans"]["stars_packs"][:4] == [50, 75, 100, 150]
        bad_requests = (
            {"channel_ids": []}, {"channel_ids": [seeded.channel_id, seeded.channel_id]},
            {"posts_per_day": True}, {"stars": "124"}, {"posts_per_day": 7},
        )
        for bad in bad_requests:
            assert (await buy(**bad)).status == 400, bad
        assert (await buy(channel_ids=[seeded.channel_id, foreign_id])).status == 404
        resp = await buy(stars=100)
        assert resp.status == 409 and (await resp.json())["stars"] == 124
        resp = await buy(round_to_pack=True, stars=150)
        assert resp.status == 402 and (await resp.json())["missing"] == 150

        async with sessionmaker() as session:
            await credit(session, seeded.user_id, 500, bucket="main", kind="topup")
            await session.commit()

        data = await (await buy(round_to_pack=True, stars=150)).json()
        assert (data["balance"], data["days"]) == (350, 36)
        detail = await (await client.get(f"/api/channels/{seeded.channel_id}", headers=auth)).json()
        assert (detail["plan"], detail["posts_per_day"], detail["days_left"]) == ("paid", 15, 36)
        remaining = (await (await client.get(f"/api/limits/{seeded.channel_id}", headers=auth)).json())["remaining"]
        assert remaining == {"wm_photo": 540, "wm_video": 90, "ai_text": 540}

        # 36 unused days of the 124★ plan are worth ~22.4 days of the 199★ plan, plus the 30 bought.
        data = await (await buy(posts_per_day=50, stars=199)).json()
        assert data["balance"] == 151
        detail = await (await client.get(f"/api/channels/{seeded.channel_id}", headers=auth)).json()
        assert (detail["posts_per_day"], detail["days_left"]) == (50, 53)
    finally:
        await client.close()


async def test_calendar_week_and_move(sessionmaker, seeded):
    settings = Settings(bot_token=TOKEN, webapp_enabled=True, liqpay_enabled=False, _env_file=None)
    client = await _client(settings, sessionmaker, InvoiceBot())
    auth = {"Authorization": "tma " + init_data({"id": seeded.tg_id, "first_name": "Олена"})}
    now = utcnow()
    async with sessionmaker() as session:
        other = User(tg_id=999, trial_ends_at=now)
        session.add(other)
        await session.flush()
        foreign = Channel(owner_id=other.id, chat_id=-1005, kind="channel", title="Чужий", watermark={})
        session.add(foreign)
        await session.flush()
        upcoming = Publication(post_id=seeded.post_id, channel_id=seeded.channel_id, owner_id=seeded.user_id,
                               run_at=now + timedelta(hours=2), status="pending")
        due = Publication(post_id=seeded.post_id, channel_id=seeded.channel_id, owner_id=seeded.user_id,
                          run_at=now - timedelta(minutes=1), status="pending")
        paused = Publication(post_id=seeded.post_id, channel_id=seeded.channel_id, owner_id=seeded.user_id,
                             run_at=now - timedelta(hours=1), status="paused")
        done = Publication(post_id=seeded.post_id, channel_id=seeded.channel_id, owner_id=seeded.user_id,
                           run_at=now - timedelta(hours=3), published_at=now - timedelta(hours=3),
                           status="published", message_ids={"parts": [{"ids": [42]}]})
        cancelled = Publication(post_id=seeded.post_id, channel_id=seeded.channel_id, owner_id=seeded.user_id,
                                run_at=now + timedelta(hours=1), status="cancelled")
        theirs = Publication(post_id=seeded.post_id, channel_id=foreign.id, owner_id=other.id,
                             run_at=now + timedelta(hours=1), status="pending")
        session.add_all([upcoming, due, paused, done, cancelled, theirs])
        await session.commit()
        ids = SimpleNamespace(upcoming=upcoming.id, due=due.id, paused=paused.id, done=done.id,
                              cancelled=cancelled.id, theirs=theirs.id, foreign=foreign.id)
    try:
        page = await client.get("/app/calendar/?channel=1")
        assert page.status == 200 and 'data-app="calendar"' in await page.text()
        moved_page = await client.get("/app/calendar?channel=1", allow_redirects=False)
        assert moved_page.headers["Location"] == "/app/calendar/?channel=1"
        assert settings.calendar_url(7) is None
        with_url = Settings(bot_token=TOKEN, webapp_url_override="https://flowpost.test/app/", _env_file=None)
        assert with_url.calendar_url(7) == "https://flowpost.test/app/calendar/?channel=7"

        assert (await client.get("/api/calendar")).status == 401
        assert (await client.get(f"/api/calendar?channel={ids.foreign}", headers=auth)).status == 404
        week = await (await client.get("/api/calendar", headers=auth)).json()
        assert week["lang"] == "uk"
        assert week["channels"] == [{"id": seeded.channel_id, "title": "Наше місто"}]
        assert week["start"] <= week["today"] and 0 <= week["now"] < 1440
        by_id = {i["id"]: i for i in week["items"]}
        # The listing may miss items that fall in the neighbouring week around Monday midnight.
        assert ids.cancelled not in by_id and ids.theirs not in by_id
        if ids.done in by_id:
            item = by_id[ids.done]
            assert item["status"] == "published" and item["link"] == "https://t.me/nashe_misto/42"
        if ids.upcoming in by_id:
            item = by_id[ids.upcoming]
            assert (item["text"], item["icon"], item["link"]) == ("Новина дня", "📝", None)

        async def move(pub_ids, day="2099-01-05", hm="09:30"):
            return await client.post("/api/calendar/move", json={"ids": pub_ids, "date": day, "time": hm}, headers=auth)

        assert (await move([ids.upcoming], hm="9:30")).status == 400
        assert (await move([ids.upcoming], day="2020-01-01")).status == 400
        assert (await move([])).status == 400
        for blocked in (ids.due, ids.done, ids.cancelled, ids.theirs):
            assert (await move([ids.upcoming, blocked])).status == 409
        async with sessionmaker() as session:
            assert (await session.get(Publication, ids.upcoming)).run_at == upcoming.run_at

        assert (await move([ids.upcoming, ids.paused])).status == 200
        async with sessionmaker() as session:
            moved = [await session.get(Publication, i) for i in (ids.upcoming, ids.paused)]
        # 09:30 in Kyiv (UTC+2 in January) is 07:30 UTC; a paused publication stays paused.
        assert [p.run_at.strftime("%Y-%m-%d %H:%M") for p in moved] == ["2099-01-05 07:30"] * 2
        assert [p.status for p in moved] == ["pending", "paused"]

        later = await (await client.get("/api/calendar?start=2099-01-07", headers=auth)).json()
        assert later["start"] == "2099-01-05"
        assert [(i["id"], i["date"], i["time"]) for i in later["items"]] == [
            (ids.upcoming, "2099-01-05", "09:30"), (ids.paused, "2099-01-05", "09:30"),
        ]
    finally:
        await client.close()
