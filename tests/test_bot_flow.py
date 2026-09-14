"""End-to-end: real Dispatcher + handlers + DB, with Telegram API calls answered by a mocked session."""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, PhotoSize, Update, User as TgUser, Video
from sqlalchemy import select

from flowpost.bot.callbacks import Cp, Cs, Ed, Ep, St
from flowpost.bot.setup import build_dispatcher
from flowpost.db.models import Channel, Post, Publication, RepeatRule, Subscription, User
from flowpost.db.types import utcnow
from flowpost.services.ai import AIService
from flowpost.services.publisher import Publisher
from flowpost.services.slots import local_now
from flowpost.services.worker import Worker

BOT_ID = 123456
USER_ID = 777
CHANNEL_CHAT = -1009876543210


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

    def _from(self):
        return {"id": USER_ID, "is_bot": False, "first_name": "Олена", "language_code": "uk"}

    async def feed(self, **payload):
        update = Update.model_validate({"update_id": next(self._update_ids), **payload}, context={"bot": self.bot})
        result = await self.dp.feed_update(self.bot, update)
        return result

    def _message(self, **fields) -> dict:
        return {"message_id": next(self._msg_ids), "date": int(datetime.now().timestamp()),
                "chat": {"id": USER_ID, "type": "private"}, "from": self._from(), **fields}

    async def text(self, text: str):
        await self.feed(message=self._message(text=text))

    async def photo(self, file_id="user-photo"):
        await self.feed(message=self._message(photo=[{"file_id": file_id, "file_unique_id": file_id, "width": 800, "height": 600}]))

    async def click(self, data: CallbackData):
        """Press an inline button; fails the test if no handler picked the callback up."""
        before = len(self.session.calls)
        await self.feed(callback_query={
            "id": str(next(self._update_ids)), "from": self._from(), "chat_instance": "ci", "data": data.pack(),
            "message": {"message_id": 999, "date": int(datetime.now().timestamp()),
                        "chat": {"id": USER_ID, "type": "private"}, "text": "panel"},
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

    # Відкласти: date switch, slots page, slot pick, manual input with a wrong format, confirmation
    tomorrow = local_now("Europe/Kyiv").date() + timedelta(days=1)
    ordinal = tomorrow.toordinal()
    await h.click(Ed(a="sch", p=p))
    await h.click(Ed(a="sch", p=p, v=f"{ordinal}_1"))
    # Typing a time directly on the schedule screen (without pressing "Вибрати годину та хвилини")
    # must be treated as a time, not as new post content.
    h.session.clear()
    await h.text("23:10")
    assert "Запланувати" in h.session.texts()
    assert (await _post(h)).parts[0].text_html != "23:10"
    await h.click(Ed(a="sch", p=p, v=f"{ordinal}_1"))
    await h.click(Ed(a="slot", p=p, v=f"{ordinal}_0930"))
    await h.click(Ed(a="schman", p=p, v=str(ordinal)))
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

    # Редагувати пост → save changes into the channel
    await h.text("/edit")
    await h.click(Ep(a="open", id=p))
    await h.text("Виправлений текст")
    h.session.clear()
    await h.click(Ed(a="save", p=p))
    assert {"EditMessageMedia", "EditMessageText"} & set(h.session.names())


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

    # subscription screen builds a Stars invoice link
    h.session.clear()
    await h.text("/subscribe")
    assert "CreateInvoiceLink" in h.session.names()

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

    # Stars payment: pre-checkout approved, successful payment activates the subscription
    user = await _user(h)
    h.session.clear()
    await h.feed(pre_checkout_query={"id": "pcq", "from": h._from(), "currency": "XTR", "total_amount": 350,
                                     "invoice_payload": f"flowpost-sub:{user.id}"})
    assert any(n == "AnswerPreCheckoutQuery" and m.ok for n, m in h.session.calls)
    expires = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
    await h.feed(message=h._message(successful_payment={
        "currency": "XTR", "total_amount": 350, "invoice_payload": f"flowpost-sub:{user.id}",
        "telegram_payment_charge_id": "charge-1", "provider_payment_charge_id": "",
        "subscription_expiration_date": expires, "is_recurring": True, "is_first_recurring": True,
    }))
    sub = await h.db(lambda s: s.scalar(select(Subscription)))
    assert sub.provider == "stars" and sub.provider_sub_id == "charge-1" and sub.current_period_end > utcnow()

    # now publishing works
    await h.click(Ed(a="pub", p=p))
    await h.click(Ed(a="pubok", p=p))
    assert await h.db(lambda s: s.scalar(select(Publication).where(Publication.status == "published")))
