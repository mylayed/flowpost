"""End-to-end: real Dispatcher + handlers + DB, with Telegram API calls answered by a mocked session."""
from __future__ import annotations

import itertools
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, PhotoSize, Update, User as TgUser, Video
from sqlalchemy import select, update

from flowpost.bot.callbacks import Bl, Ca, Cp, Cs, Ed, Ep, Pj, St
from flowpost.bot.handlers.channel_settings import stats_view
from flowpost.bot.setup import build_dispatcher
from flowpost.config import Settings
from flowpost.db.models import Channel, ChannelAdmin, Post, PostPart, PostTarget, Publication, RepeatRule, \
    Subscription, User
from flowpost.db.types import utcnow
from flowpost.services.ai import AIService
from flowpost.services.publisher import Publisher
from flowpost.services.slots import local_now
from flowpost.services.worker import Worker
from flowpost.web import process_liqpay_payload

BOT_ID = 123456
USER_ID = 777
ADMIN_ID = 888
CHANNEL_CHAT = -1009876543210
DISCUSSION_CHAT = -1005551234567


class MockSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list = []
        self._ids = itertools.count(1000)

    def _message(self, chat_id, **extra) -> Message:
        return Message(
            message_id=next(self._ids),
            date=datetime.now(timezone.utc),
            chat=Chat(id=chat_id if isinstance(chat_id, int) else USER_ID, type="private"),
            **extra,
        )

    async def make_request(self, bot, method, timeout=None):
        name = type(method).__name__
        self.calls.append((name, method))
        chat_id = getattr(method, "chat_id", USER_ID)
        if name == "SendPhoto":
            return self._message(chat_id, photo=[PhotoSize(file_id="sent-photo", file_unique_id="u", width=10, height=10)])
        if name == "SendVideo":
            return self._message(chat_id, video=Video(file_id="sent-video", file_unique_id="v", width=10, height=10, duration=1))
        if name == "SendMediaGroup":
            result = []
            for item in method.media:
                if type(item).__name__ == "InputMediaPhoto":
                    result.append(self._message(chat_id, photo=[PhotoSize(file_id="g", file_unique_id="g", width=1, height=1)]))
                else:
                    result.append(self._message(chat_id, video=Video(file_id="gv", file_unique_id="gv", width=1, height=1, duration=1)))
            return result
        if name in ("SendMessage", "SendAnimation", "SendDocument", "SendAudio", "EditMessageText",
                    "EditMessageCaption", "EditMessageMedia"):
            return self._message(chat_id)
        if name == "GetMe":
            return TgUser(id=BOT_ID, is_bot=True, first_name="FlowPost", username="flowpost_bot")
        if name == "GetChatMember":
            if method.user_id == BOT_ID:
                return SimpleNamespace(status="administrator", can_post_messages=True)
            return SimpleNamespace(status="creator")
        if name == "GetChat":
            return SimpleNamespace(id=method.chat_id, type="channel", title="Test Channel", username="testchan", is_forum=False)
        if name == "CreateInvoiceLink":
            return "https://t.me/$invoice"
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover - not used
        yield b""

    async def close(self):
        pass

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]

    def texts(self) -> str:
        return "\n".join(str(getattr(m, "text", "") or getattr(m, "caption", "") or "") for _, m in self.calls)

    def clear(self):
        self.calls.clear()


class Harness:
    def __init__(self, dp, bot, session, sessionmaker):
        self.dp, self.bot, self.session, self.sm = dp, bot, session, sessionmaker
        self._update_ids = itertools.count(1)
        self._msg_ids = itertools.count(1)

    def _from(self, uid: int = USER_ID):
        name = "Олена" if uid == USER_ID else f"User{uid}"
        return {"id": uid, "is_bot": False, "first_name": name, "language_code": "uk"}

    async def feed(self, **payload):
        update = Update.model_validate({"update_id": next(self._update_ids), **payload}, context={"bot": self.bot})
        result = await self.dp.feed_update(self.bot, update)
        return result

    def _message(self, uid: int = USER_ID, **fields) -> dict:
        return {"message_id": next(self._msg_ids), "date": int(datetime.now().timestamp()),
                "chat": {"id": uid, "type": "private"}, "from": self._from(uid), **fields}

    async def text(self, text: str, uid: int = USER_ID):
        await self.feed(message=self._message(uid, text=text))

    async def photo(self, file_id="user-photo", uid: int = USER_ID):
        await self.feed(message=self._message(uid, photo=[{"file_id": file_id, "file_unique_id": file_id, "width": 800, "height": 600}]))

    async def click(self, data: CallbackData, uid: int = USER_ID):
        """Press an inline button; fails the test if no handler picked the callback up."""
        before = len(self.session.calls)
        await self.feed(callback_query={
            "id": str(next(self._update_ids)), "from": self._from(uid), "chat_instance": "ci", "data": data.pack(),
            "message": {"message_id": 999, "date": int(datetime.now().timestamp()),
                        "chat": {"id": uid, "type": "private"}, "text": "panel"},
        })
        assert len(self.session.calls) > before, f"callback {data.pack()} was not handled"

    async def db(self, fn):
        async with self.sm() as session:
            return await fn(session)


@pytest.fixture
async def h(sessionmaker, settings):
    session = MockSession()
    bot = Bot("123456:TEST", session=session, default=DefaultBotProperties(parse_mode="HTML"))
    publisher = Publisher(bot, None)
    dp = build_dispatcher(settings, sessionmaker, MemoryStorage())
    dp.workflow_data.update(settings=settings, publisher=publisher, worker=Worker(bot, sessionmaker, publisher, settings),
                            ai=AIService(settings))
    yield Harness(dp, bot, session, sessionmaker)
    # Handler routers are module-level singletons: detach them so the next test can build a fresh Dispatcher.
    for router in dp.sub_routers:
        router._parent_router = None


async def _post(h: Harness) -> Post:
    async def q(s):
        return (await s.scalars(select(Post).order_by(Post.id.desc()))).first()
    return await h.db(q)


async def _user(h: Harness) -> User:
    return await h.db(lambda s: s.scalar(select(User).where(User.tg_id == USER_ID)))


async def test_full_editor_flow(h: Harness):
    # /start registers the tenant with a trial and shows the main reply keyboard
    await h.text("/start")
    user = await _user(h)
    assert user is not None and user.trial_ends_at > utcnow()

    # connect a channel through the native chat picker
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    channel = await h.db(lambda s: s.scalar(select(Channel)))
    assert channel.chat_id == CHANNEL_CHAT and channel.is_active
    c = channel.id

    # sending a photo starts a post; a following text becomes its caption
    h.session.clear()
    await h.photo()
    post = await _post(h)
    p = post.id
    assert post.parts[0].media[0]["file_id"] == "user-photo"
    assert "SendPhoto" in h.session.names()  # preview
    await h.text("Сирий текст новини")
    assert (await _post(h)).parts[0].text_html == "Сирий текст новини"

    # Кнопки: wrong format shows an example, correct format is saved
    await h.click(Ed(a="btn", p=p))
    await h.click(Ed(a="btn_set", p=p))
    h.session.clear()
    await h.text("просто текст")
    assert "Приклад" in h.session.texts()
    await h.text("Читати далі — https://t.me/testchan")
    assert (await _post(h)).parts[0].buttons == [[{"text": "Читати далі", "url": "https://t.me/testchan"}]]

    # Медіа: add a second photo → album, reorder
    await h.click(Ed(a="media", p=p))
    await h.click(Ed(a="m_add", p=p))
    await h.photo(file_id="second-photo")
    await h.click(Ed(a="m_up", p=p, v="1"))
    h.session.clear()
    await h.click(Ed(a="m_done", p=p))
    assert [m["file_id"] for m in (await _post(h)).parts[0].media] == ["second-photo", "user-photo"]
    assert "SendMediaGroup" in h.session.names()
    assert "SendMessage" in h.session.names()  # album + buttons → separate message with buttons

    # Автопідпис + Водяний знак (channel-level menus opened from the editor)
    await h.click(Ed(a="sig", p=p))
    await h.click(Cs(a="sig_post", c=c, p=p))
    assert (await _post(h)).options["signature"] is False
    await h.click(Cs(a="sig_post", c=c, p=p))
    await h.click(Ed(a="wm", p=p))
    await h.click(Cs(a="wm_text", c=c, p=p))
    await h.text("@testchan")
    await h.click(Cs(a="wm_pos", c=c, p=p, v="tl"))
    await h.click(Cs(a="wm_op", c=c, p=p, v="-10"))
    channel = await h.db(lambda s: s.get(Channel, c))
    assert channel.watermark["text"] == "@testchan" and channel.watermark["position"] == "tl"
    assert channel.watermark["opacity"] == 50
    assert (await _post(h)).options["watermark"] is True

    # Сповіщення про публікацію: off by default, togglable, with a choice of recipients
    channel = await h.db(lambda s: s.get(Channel, c))
    assert channel.notify_published is False and channel.notify_recipients == "owner"
    await h.click(Pj(a="ch", c=c))
    await h.click(Cs(a="notify_def", c=c))
    await h.click(Cs(a="notify_rcpt", c=c, v="admin"))
    channel = await h.db(lambda s: s.get(Channel, c))
    assert channel.notify_published is True and channel.notify_recipients == "admin"

    # ШІ-асистент without an API key: menu opens, a run reports that AI is not configured
    await h.click(Ed(a="ai", p=p))
    h.session.clear()
    await h.click(Ed(a="ai_run", p=p, v="format"))
    assert "не налаштований" in h.session.texts()

    # Більше налаштувань
    await h.click(Ed(a="more", p=p))
    await h.click(Ed(a="mo_t", p=p, v="silent"))
    await h.click(Ed(a="mo_pin", p=p))
    await h.click(Ed(a="mo_delc", p=p))
    await h.text("12")
    opts = (await _post(h)).options
    assert opts["silent"] is True and opts["pin"] is True and opts["auto_delete_hours"] == 12

    # Повідомлення (серія)
    await h.click(Ed(a="parts", p=p))
    await h.click(Ed(a="pt_add", p=p))
    await h.text("Друге повідомлення")
    post = await _post(h)
    assert len(post.parts) == 2 and post.parts[1].text_html == "Друге повідомлення"
    await h.click(Ed(a="part", p=p, v="0"))

    # Автоповтор
    await h.click(Ed(a="rep", p=p))
    await h.click(Ed(a="rp_i", p=p, v="4320"))
    await h.click(Ed(a="rp_c", p=p, v="3"))
    await h.click(Ed(a="rp_dp", p=p))
    rule = await h.db(lambda s: s.scalar(select(RepeatRule)))
    assert (rule.interval_minutes, rule.remaining_count, rule.delete_previous, rule.active) == (4320, 3, True, True)

    # Мультипостинг: only one channel → the last one can't be deselected
    await h.click(Ed(a="multi", p=p))
    await h.click(Ed(a="mt", p=p, v=str(c)))
    assert (await _post(h)).channel_ids == [c]

    # Відкласти: date switch, slots page, slot pick, typed time (wrong then right format), confirmation
    tomorrow = local_now("Europe/Kyiv").date() + timedelta(days=1)
    ordinal = tomorrow.toordinal()
    await h.click(Ed(a="sch", p=p))
    await h.click(Ed(a="sch", p=p, v=f"{ordinal}_1"))
    # Typing a time directly on the schedule screen (there's no separate "manual entry" button)
    # must be treated as a time, not as new post content.
    h.session.clear()
    await h.text("23:10")
    assert "Запланувати" in h.session.texts()
    assert (await _post(h)).parts[0].text_html != "23:10"
    await h.click(Ed(a="sch", p=p, v=f"{ordinal}_1"))
    await h.click(Ed(a="slot", p=p, v=f"{ordinal}_0930"))
    h.session.clear()
    await h.text("25:99")
    assert "Неправильний формат" in h.session.texts()
    await h.text("10:15")
    assert "Запланувати" in h.session.texts()
    await h.click(Ed(a="schok", p=p, v=f"{ordinal}_1015"))
    pubs = list(await h.db(lambda s: s.scalars(select(Publication))))
    assert len(pubs) == 1 and pubs[0].status == "pending"
    assert (await _post(h)).status == "scheduled"

    # Контент-план shows it; «publish now» delivers into the channel
    await h.text("🗓 Контент-план")  # opens today
    h.session.clear()
    await h.click(Cp(a="day", d=ordinal))  # ▶️ to tomorrow
    assert any("10:15" in str(getattr(m, "reply_markup", "")) for _, m in h.session.calls)
    await h.click(Cp(a="post", d=ordinal, id=p))
    await h.click(Cp(a="now", d=ordinal, id=p))
    pub = await h.db(lambda s: s.scalar(select(Publication).where(Publication.status == "published")))
    assert pub is not None and pub.message_ids["parts"]
    channel_calls = [m for _, m in h.session.calls if getattr(m, "chat_id", None) == CHANNEL_CHAT]
    assert any(type(m).__name__ == "SendMediaGroup" for m in channel_calls)
    assert any(type(m).__name__ == "PinChatMessage" for m in channel_calls)
    assert (await _post(h)).status == "scheduled"  # auto-repeat queued the next run

    # Контент-план → «Опубліковані» tab shows the delivered post, editable but not reschedulable
    today_ordinal = local_now("Europe/Kyiv").date().toordinal()
    h.session.clear()
    await h.click(Cp(a="day", d=today_ordinal, m="p"))
    assert "SendMessage" in h.session.names() or "EditMessageText" in h.session.names()
    kb_text = str(h.session.calls[-1][1].reply_markup)
    assert "Опубліковані" in kb_text
    await h.click(Cp(a="post", d=today_ordinal, id=p, m="p"))
    post_kb = str(h.session.calls[-1][1].reply_markup)
    assert "Редагувати" in post_kb
    assert "Перенести" not in post_kb and "Опублікувати зараз" not in post_kb and "Скасувати" not in post_kb

    # Редагувати пост → save changes into the channel
    await h.text("/edit")
    await h.click(Ep(a="open", id=p))
    await h.text("Виправлений текст")
    h.session.clear()
    await h.click(Ed(a="save", p=p))
    assert {"EditMessageMedia", "EditMessageText"} & set(h.session.names())


async def test_channel_admin_delegation(h: Harness):
    """Owner invites an admin; the admin posts into the owner's channel under the owner's account/subscription."""
    await h.text("/start")
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    channel = await h.db(lambda s: s.scalar(select(Channel)))
    c = channel.id
    owner = await _user(h)

    # Owner creates an invite: posting + settings, but not disconnect
    await h.click(Pj(a="ch", c=c))
    await h.click(Ca(a="list", c=c))
    await h.click(Ca(a="new", c=c, v="100"))
    await h.click(Ca(a="toggle", c=c, id=1, v="100"))  # settings on → "110"
    h.session.clear()
    await h.click(Ca(a="create", c=c, v="110"))
    invite_text = h.session.calls[-1][1].text
    token = re.search(r"adm_([0-9a-f]+)", invite_text).group(1)

    # A different Telegram user redeems the invite via /start
    await h.text(f"/start adm_{token}", uid=ADMIN_ID)
    admin_user = await h.db(lambda s: s.scalar(select(User).where(User.tg_id == ADMIN_ID)))
    grant = await h.db(lambda s: s.scalar(
        select(ChannelAdmin).where(ChannelAdmin.channel_id == c, ChannelAdmin.user_id == admin_user.id)
    ))
    assert grant is not None and grant.can_posts and grant.can_settings and not grant.can_disconnect

    # The admin's own trial is expired — publishing must still work off the owner's active access
    async def expire_admin(s):
        await s.execute(update(User).where(User.id == admin_user.id).values(trial_ends_at=utcnow() - timedelta(minutes=1)))
        await s.commit()
    await h.db(expire_admin)

    # Admin creates and publishes a post into the delegated channel — it belongs to the real owner
    await h.text("Пост від адміністратора", uid=ADMIN_ID)
    post = await _post(h)
    assert post.owner_id == owner.id
    p = post.id
    await h.click(Ed(a="pub", p=p), uid=ADMIN_ID)
    await h.click(Ed(a="pubok", p=p), uid=ADMIN_ID)
    pub = await h.db(lambda s: s.scalar(
        select(Publication).where(Publication.post_id == p, Publication.status == "published")
    ))
    assert pub is not None

    # No can_disconnect → the admin can't disconnect the channel
    h.session.clear()
    await h.click(Pj(a="off", c=c), uid=ADMIN_ID)
    assert any(n == "AnswerCallbackQuery" and m.show_alert for n, m in h.session.calls)

    # Owner revokes access; the ex-admin can no longer reach that post
    await h.click(Pj(a="ch", c=c))
    await h.click(Ca(a="list", c=c))
    await h.click(Ca(a="remove", c=c, id=grant.id))
    await h.click(Ca(a="removeok", c=c, id=grant.id))
    assert await h.db(lambda s: s.get(ChannelAdmin, grant.id)) is None
    h.session.clear()
    await h.click(Ed(a="home", p=p), uid=ADMIN_ID)
    assert any(n == "AnswerCallbackQuery" and m.show_alert for n, m in h.session.calls)


async def test_empty_post_blocks_schedule_and_publish(h: Harness):
    await h.text("/start")
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    await h.text("Тимчасовий текст")
    p = (await _post(h)).id

    async def empty_out(s):
        post = await s.get(Post, p)
        post.parts[0].text_html = ""
        post.parts[0].media = []
        await s.commit()
    await h.db(empty_out)

    h.session.clear()
    await h.click(Ed(a="sch", p=p))
    assert any(n == "AnswerCallbackQuery" and m.show_alert for n, m in h.session.calls)
    assert "SendMessage" not in h.session.names() and "EditMessageText" not in h.session.names()

    h.session.clear()
    await h.click(Ed(a="pub", p=p))
    assert any(n == "AnswerCallbackQuery" and m.show_alert for n, m in h.session.calls)
    assert await h.db(lambda s: s.scalar(select(Publication))) is None


async def test_cancel_settings_billing_and_paywall(h: Harness):
    await h.text("/start")
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))

    # a text draft, then «Скасувати і назад» deletes it
    await h.text("Чернетка")
    p = (await _post(h)).id
    await h.click(Ed(a="cancel", p=p))
    await h.click(Ed(a="cancelok", p=p))
    assert await h.db(lambda s: s.get(Post, p)) is None

    # settings: language and time zone
    await h.text("/settings")
    await h.click(St(a="lang"))
    await h.click(St(a="tzset", v="Europe/Warsaw"))
    user = await _user(h)
    assert (user.lang, user.tz) == ("en", "Europe/Warsaw")
    await h.click(St(a="lang"))

    # subscription screen offers a LiqPay checkout link
    h.session.clear()
    await h.text("/subscribe")
    sent = next(m for n, m in h.session.calls if n == "SendMessage")
    urls = [b.url for row in sent.reply_markup.inline_keyboard for b in row if b.url]
    assert any("liqpay.ua" in u for u in urls)

    # trial over → publishing is blocked by the paywall
    async def expire(s):
        u = await s.scalar(select(User).where(User.tg_id == USER_ID))
        u.trial_ends_at = utcnow() - timedelta(minutes=1)
        await s.commit()
    await h.db(expire)
    await h.text("Пост без підписки")
    p = (await _post(h)).id
    h.session.clear()
    await h.click(Ed(a="pubok", p=p))
    assert any(n == "AnswerCallbackQuery" and m.show_alert for n, m in h.session.calls)
    assert await h.db(lambda s: s.scalar(select(Publication))) is None

    # LiqPay payment: server-to-server callback activates the subscription
    user = await _user(h)
    payload = {"status": "success", "order_id": f"flowpost-{user.id}-abc", "payment_id": "charge-1",
               "amount": 5, "currency": "USD"}
    await process_liqpay_payload(payload, h.sm, None)
    sub = await h.db(lambda s: s.scalar(select(Subscription)))
    assert sub.provider == "liqpay" and sub.current_period_end > utcnow()

    # now publishing works
    await h.click(Ed(a="pub", p=p))
    await h.click(Ed(a="pubok", p=p))
    assert await h.db(lambda s: s.scalar(select(Publication).where(Publication.status == "published")))


async def test_manual_transfer_flow(sessionmaker):
    settings = Settings(
        bot_token="123456:TEST", admin_ids=str(ADMIN_ID), payment_requisites="IBAN: UA000",
        liqpay_enabled=False, _env_file=None,
    )
    session = MockSession()
    bot = Bot("123456:TEST", session=session, default=DefaultBotProperties(parse_mode="HTML"))
    dp = build_dispatcher(settings, sessionmaker, MemoryStorage())
    dp.workflow_data.update(settings=settings, publisher=Publisher(bot, None),
                            worker=Worker(bot, sessionmaker, Publisher(bot, None), settings), ai=AIService(settings))
    h = Harness(dp, bot, session, sessionmaker)
    try:
        await h.text("/start")
        h.session.clear()
        await h.text("/subscribe")
        await h.click(Bl(a="manual"))
        assert "IBAN: <code>UA000</code>" in h.session.texts()

        h.session.clear()
        await h.feed(message=h._message(photo=[{"file_id": "receipt", "file_unique_id": "receipt",
                                                 "width": 100, "height": 100}]))
        names = h.session.names()
        assert names.count("ForwardMessage") == 1 and "SendMessage" in names
        assert "id 777" in h.session.texts()
        assert h.session.texts().count("Дякуємо") == 1

        # a second message once the state is cleared is not treated as a receipt anymore
        h.session.clear()
        await h.text("дякую")
        assert "ForwardMessage" not in h.session.names()
    finally:
        for router in dp.sub_routers:
            router._parent_router = None


async def test_grant_notifies_user_and_shows_days_left(sessionmaker):
    settings = Settings(bot_token="123456:TEST", admin_ids=str(ADMIN_ID), liqpay_enabled=False, _env_file=None)
    session = MockSession()
    bot = Bot("123456:TEST", session=session, default=DefaultBotProperties(parse_mode="HTML"))
    dp = build_dispatcher(settings, sessionmaker, MemoryStorage())
    dp.workflow_data.update(settings=settings, publisher=Publisher(bot, None),
                            worker=Worker(bot, sessionmaker, Publisher(bot, None), settings), ai=AIService(settings))
    h = Harness(dp, bot, session, sessionmaker)
    try:
        await h.text("/start")

        async def expire(s):
            u = await s.scalar(select(User).where(User.tg_id == USER_ID))
            u.trial_ends_at = utcnow() - timedelta(minutes=1)
            await s.commit()
        await h.db(expire)

        # a bare /grant (e.g. from tapping the command in a forwarded receipt) must not crash:
        # Telegram's HTML parser rejects "<...>" placeholders, so the usage text must avoid them.
        h.session.clear()
        await h.text("/grant", uid=ADMIN_ID)
        usage_reply = next(m for n, m in h.session.calls if n == "SendMessage" and m.chat_id == ADMIN_ID)
        assert "Usage" in usage_reply.text and "<" not in usage_reply.text

        h.session.clear()
        await h.text(f"/grant {USER_ID} 30", uid=ADMIN_ID)
        admin_reply = next(m for n, m in h.session.calls if n == "SendMessage" and m.chat_id == ADMIN_ID)
        assert "active" in admin_reply.text
        user_notice = next(m for n, m in h.session.calls if n == "SendMessage" and m.chat_id == USER_ID)
        assert "Підписку активовано" in user_notice.text

        h.session.clear()
        await h.text("/settings")
        assert "ще 29 дн." in h.session.texts() or "ще 30 дн." in h.session.texts()
    finally:
        for router in dp.sub_routers:
            router._parent_router = None


async def _seed_published(h: Harness, *, message_id: int, discussion_thread_id: int | None = None) -> tuple[int, int]:
    """A channel with a post already published as one message; returns (channel_id, publication_id)."""
    async def create(session):
        user = User(tg_id=USER_ID, lang="uk", tz="Europe/Kyiv", trial_ends_at=utcnow() + timedelta(days=7))
        session.add(user)
        await session.flush()
        channel = Channel(owner_id=user.id, chat_id=CHANNEL_CHAT, kind="channel", title="Test Channel",
                          username="testchan", watermark={}, discussion_chat_id=DISCUSSION_CHAT)
        session.add(channel)
        await session.flush()
        post = Post(owner_id=user.id, status="published")
        post.parts = [PostPart(position=0, text_html="Новина дня", media=[], buttons=[])]
        post.targets = [PostTarget(channel_id=channel.id, position=0)]
        session.add(post)
        await session.flush()
        pub = Publication(post_id=post.id, channel_id=channel.id, owner_id=user.id, run_at=utcnow(),
                          status="published", published_at=utcnow(), notify=False,
                          message_ids={"parts": [{"ids": [message_id]}]}, discussion_thread_id=discussion_thread_id)
        session.add(pub)
        await session.commit()
        return channel.id, pub.id
    return await h.db(create)


async def test_reaction_count_updates_publication(h: Harness):
    _, pub_id = await _seed_published(h, message_id=4242)
    await h.feed(message_reaction_count={
        "chat": {"id": CHANNEL_CHAT, "type": "channel", "title": "Test Channel"},
        "message_id": 4242,
        "date": int(datetime.now().timestamp()),
        "old_reaction": [],
        "new_reaction": [],
        "reactions": [{"type": {"type": "emoji", "emoji": "👍"}, "total_count": 3}],
    })
    pub = await h.db(lambda s: s.get(Publication, pub_id))
    assert pub.reactions == {"4242": {"👍": 3}}


async def test_discussion_reply_counts_as_comment(h: Harness):
    _, pub_id = await _seed_published(h, message_id=4242, discussion_thread_id=9001)
    await h.feed(message={
        "message_id": next(h._msg_ids), "date": int(datetime.now().timestamp()),
        "chat": {"id": DISCUSSION_CHAT, "type": "supergroup", "title": "Discuss"},
        "message_thread_id": 9001, "from": {"id": 999, "is_bot": False, "first_name": "Reader"},
        "text": "Класно!",
    })
    pub = await h.db(lambda s: s.get(Publication, pub_id))
    assert pub.comments_count == 1

    # the automatic-forward copy that opens the thread must never be counted as a comment on itself
    await h.feed(message={
        "message_id": 9001, "date": int(datetime.now().timestamp()),
        "chat": {"id": DISCUSSION_CHAT, "type": "supergroup", "title": "Discuss"},
        "message_thread_id": 9001, "is_automatic_forward": True,
        "from": {"id": BOT_ID, "is_bot": True, "first_name": "Test Channel"},
        "forward_origin": {"type": "channel", "chat": {"id": CHANNEL_CHAT, "type": "channel", "title": "Test Channel"},
                           "message_id": 4242, "date": int(datetime.now().timestamp())},
        "text": "Новина дня", "is_topic_message": True,
    })
    pub = await h.db(lambda s: s.get(Publication, pub_id))
    assert pub.comments_count == 1
    assert pub.discussion_thread_id == 9001


async def test_moderation_deletes_spam_comment_and_skips_the_count(h: Harness):
    _, pub_id = await _seed_published(h, message_id=4242, discussion_thread_id=9001)
    await h.feed(message={
        "message_id": next(h._msg_ids), "date": int(datetime.now().timestamp()),
        "chat": {"id": DISCUSSION_CHAT, "type": "supergroup", "title": "Discuss"},
        "message_thread_id": 9001, "from": {"id": 999, "is_bot": False, "first_name": "Spammer"},
        "text": "Заходь на t.me/some_scam, там круто!",
    })
    assert "DeleteMessage" in h.session.names()
    pub = await h.db(lambda s: s.get(Publication, pub_id))
    assert pub.comments_count == 0


async def test_moderation_can_be_disabled_per_channel(h: Harness):
    channel_id, pub_id = await _seed_published(h, message_id=4242, discussion_thread_id=9001)

    async def disable(s):
        await s.execute(update(Channel).where(Channel.id == channel_id).values(moderation={"enabled": False}))
        await s.commit()
    await h.db(disable)
    await h.feed(message={
        "message_id": next(h._msg_ids), "date": int(datetime.now().timestamp()),
        "chat": {"id": DISCUSSION_CHAT, "type": "supergroup", "title": "Discuss"},
        "message_thread_id": 9001, "from": {"id": 999, "is_bot": False, "first_name": "Spammer"},
        "text": "Заходь на t.me/some_scam, там круто!",
    })
    assert "DeleteMessage" not in h.session.names()
    pub = await h.db(lambda s: s.get(Publication, pub_id))
    assert pub.comments_count == 1


async def test_stats_view_summarizes_engagement(h: Harness):
    channel_id, pub_id = await _seed_published(h, message_id=4242)
    async def add_engagement(session):
        pub = await session.get(Publication, pub_id)
        pub.reactions = {"4242": {"👍": 3, "❤️": 2}}
        pub.comments_count = 4
        await session.commit()
    await h.db(add_engagement)

    async def render(session):
        channel = await session.get(Channel, channel_id)
        user = await session.scalar(select(User).where(User.tg_id == USER_ID))
        return await stats_view(session, channel, user, 7)
    text, _ = await h.db(render)
    assert "Реакції: 5" in text and "Коментарі: 4" in text and "Новина дня" in text
