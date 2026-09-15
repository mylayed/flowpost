from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import select

from flowpost.config import Settings
from flowpost.db.models import (
    BalanceEntry, Channel, ChannelQuota, ChannelSubscription, Payment, Post, Publication, User,
)
from flowpost.db.types import utcnow
from flowpost.services.billing.stars import parse_payload
from flowpost.services.billing.wallet import apply_topup, cashback_for, credit
from flowpost.web import build_web_app
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
        assert catalog["channel_discounts"][-1] == [100, 30] and catalog["trial"]["days"] == 14
        terms = await (await client.get("/api/terms", headers=auth)).json()
        assert "FlowPost" in terms["html"]

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
        assert (detail["posts_left"], detail["posts_limit"], detail["posts_window"]) == (48, 50, "trial")
        assert detail["title"] == "Арабаба" and detail["link"] == "https://t.me/c/777"
        assert (await client.get(f"/api/channels/{foreign_id}", headers=auth)).status == 404

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
