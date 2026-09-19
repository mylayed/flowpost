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
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, PhotoSize, Update, User as TgUser, Video
from sqlalchemy import select, update

from flowpost.bot.callbacks import Bl, Ca, Cp, Cs, Ed, Ep, Fd, Nc, Pj, St
from flowpost.bot.handlers.channel_settings import stats_view
from flowpost.bot.setup import build_dispatcher
from flowpost.config import Settings
from flowpost.db.models import Channel, ChannelAdmin, ChannelFolder, ChannelFolderItem, Post, PostPart, \
    PostTarget, Publication, RepeatRule, Subscription, SupportThread, User
from flowpost.db.repo import stats as stats_repo
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services.ai import AIService
from flowpost.services.billing.stars import make_payload
from flowpost.services.publisher import Publisher
from flowpost.services.slots import local_now
from flowpost.services.worker import Worker
from flowpost.web import process_liqpay_payload

BOT_ID = 123456
USER_ID = 777
ADMIN_ID = 888
CHANNEL_CHAT = -1009876543210
DISCUSSION_CHAT = -1005551234567
SUPPORT_CHAT = -1004443332221


class MockSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list = []
        self._ids = itertools.count(1000)
        self.errors: dict[str, list[Exception]] = {}  # method name -> errors to raise on its next calls
        self.member_status: dict[int, str] = {}  # user id -> their status in any chat (default: creator)

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
        if self.errors.get(name):
            raise self.errors[name].pop(0)
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
            return SimpleNamespace(status=self.member_status.get(method.user_id, "creator"))
        if name == "CreateChatInviteLink":
            return SimpleNamespace(invite_link=f"https://t.me/+link{next(self._ids)}", name=method.name)
        if name == "GetChatMemberCount":
            return 1000
        if name == "GetChat":
            return SimpleNamespace(id=method.chat_id, type="channel", title="Test Channel", username="testchan", is_forum=False)
        if name == "CreateForumTopic":
            return SimpleNamespace(message_thread_id=next(self._ids), name=method.name, icon_color=0)
        if name == "CopyMessage":
            return SimpleNamespace(message_id=next(self._ids))
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

    async def in_topic(self, topic_id: int, uid: int = ADMIN_ID, chat_id: int = SUPPORT_CHAT, **fields):
        """A message from the support team inside a topic of the support group."""
        await self.feed(message={
            "message_id": next(self._msg_ids), "date": int(datetime.now().timestamp()),
            "chat": {"id": chat_id, "type": "supergroup", "title": "Support", "is_forum": True},
            "from": self._from(uid), "message_thread_id": topic_id, "is_topic_message": True, **fields,
        })

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
    assert channel.chat_id == CHANNEL_CHAT and channel.is_active and channel.trial_ends_at > utcnow()
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


async def test_album_screen_orders_replaces_and_watermarks_items(h: Harness):
    await h.text("/start")
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    c = (await h.db(lambda s: s.scalar(select(Channel)))).id
    await h.photo(file_id="p1")
    p = (await _post(h)).id

    # a single media → «Медіа» opens the plain media list
    h.session.clear()
    await h.click(Ed(a="media", p=p))
    assert "Медіа поста" in h.session.texts()
    await h.click(Ed(a="m_add", p=p))
    await h.photo(file_id="p2")
    await h.photo(file_id="p3")
    h.session.clear()
    await h.click(Ed(a="m_done", p=p))

    # with several media «Медіа» opens the album screen: one item previewed with its panel underneath
    h.session.clear()
    await h.click(Ed(a="media", p=p))
    names = h.session.names()
    assert "SendPhoto" in names and names[-1] == "SendMessage"
    assert "Медіа 1 з 3" in h.session.texts()
    await h.click(Ed(a="alb", p=p, v="1"))
    assert "Медіа 2 з 3" in h.session.texts()

    # swap 1 ↔ 3
    await h.click(Ed(a="alb_mv", p=p, v="0"))
    await h.click(Ed(a="alb_sw", p=p, v="0_2"))
    assert [m["file_id"] for m in (await _post(h)).parts[0].media] == ["p3", "p2", "p1"]

    # a sent file replaces the selected item (now index 2), keeping its slot settings
    await h.click(Ed(a="alb_wms", p=p, v="2_off"))
    await h.photo(file_id="p1-new")
    media = (await _post(h)).parts[0].media
    assert media[2]["file_id"] == "p1-new" and media[2]["wm_mode"] == "off"

    # per-item watermark: can't be switched on while nothing is configured; an own text turns it on
    h.session.clear()
    await h.click(Ed(a="alb_wms", p=p, v="1_on"))
    assert "Спершу задайте" in str(h.session.calls[-1][1])
    assert "wm_mode" not in (await _post(h)).parts[0].media[1]
    await h.click(Ed(a="alb_wm", p=p, v="1"))
    await h.click(Ed(a="alb_wmc", p=p, v="1"))
    await h.text("@mine")
    media = (await _post(h)).parts[0].media
    assert media[1]["wm_custom"]["text"] == "@mine" and media[1]["wm_mode"] == "on"
    assert "wm_custom" not in media[0]

    # album-wide: channel watermark set up, «на всі» resets per-item on/off but keeps own texts
    await h.click(Ed(a="wm", p=p))
    await h.click(Cs(a="wm_text", c=c, p=p))
    await h.text("@testchan")
    await h.click(Ed(a="alb_wma", p=p))
    await h.click(Ed(a="alb_wmall", p=p, v="on"))
    post = await _post(h)
    assert post.options["watermark"] is True
    assert all("wm_mode" not in m for m in post.parts[0].media)
    assert post.parts[0].media[1]["wm_custom"]["text"] == "@mine"

    # own watermark for all
    await h.click(Ed(a="alb_wmc", p=p, v="all"))
    await h.text("@all")
    assert all(m["wm_custom"]["text"] == "@all" for m in (await _post(h)).parts[0].media)

    # «Додати медіа в альбом» returns to the album on «Готово»
    await h.click(Ed(a="m_add", p=p, v="alb"))
    await h.photo(file_id="p4")
    h.session.clear()
    await h.click(Ed(a="m_done", p=p, v="alb"))
    assert "Медіа 4 з 4" in h.session.texts()

    # deleting down to one media drops back to the editor
    await h.click(Ed(a="alb_del", p=p, v="3"))
    await h.click(Ed(a="alb_del", p=p, v="0"))
    h.session.clear()
    await h.click(Ed(a="alb_del", p=p, v="0"))
    assert len((await _post(h)).parts[0].media) == 1
    assert "Редактор" in h.session.texts()

    # «Прибрати все медіа» from the album
    await h.click(Ed(a="m_add", p=p, v="alb"))
    await h.photo(file_id="p5")
    await h.click(Ed(a="m_done", p=p, v="alb"))
    await h.click(Ed(a="m_clear", p=p, v="alb"))
    assert (await _post(h)).parts[0].media == []


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


async def test_frequent_custom_time_becomes_a_slot(h: Harness):
    """A typed time like 10:02 shows up among the schedule slots after it's been used a few times."""
    await h.text("/start")
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    ordinal = (local_now("Europe/Kyiv").date() + timedelta(days=1)).toordinal()

    def slot_values():
        kb = [m for n, m in h.session.calls if n in ("SendMessage", "EditMessageText")][-1].reply_markup
        return [Ed.unpack(b.callback_data).v for row in kb.inline_keyboard for b in row if b.callback_data.startswith("ed:slot")]

    for i in range(3):
        await h.text(f"Пост {i}")
        p = (await _post(h)).id
        h.session.clear()
        await h.click(Ed(a="sch", p=p, v=f"{ordinal}_1"))
        assert f"{ordinal}_1002" not in slot_values()
        await h.text("10:02")
        await h.click(Ed(a="schok", p=p, v=f"{ordinal}_1002"))

    await h.text("Пост 3")
    p = (await _post(h)).id
    h.session.clear()
    await h.click(Ed(a="sch", p=p, v=f"{ordinal}_1"))  # page 2: 10:00 … 10:50
    assert slot_values()[:3] == [f"{ordinal}_1000", f"{ordinal}_1002", f"{ordinal}_1005"]


async def test_projects_hide_lost_and_delete_disconnected(h: Harness):
    """«Мої проєкти» lists only live projects: losing admin rights hides a channel, disconnecting deletes it."""
    await h.text("/start")
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    channel = await h.db(lambda s: s.scalar(select(Channel)))
    c, trial_ends_at = channel.id, channel.trial_ends_at

    def buttons():
        kb = [m for n, m in h.session.calls if n in ("SendMessage", "EditMessageText")][-1].reply_markup
        return [b.callback_data for row in kb.inline_keyboard for b in row]

    # The bot is removed from the channel → the channel drops out of the list
    def bot_status(status):
        return {"my_chat_member": {
            "chat": {"id": CHANNEL_CHAT, "type": "channel", "title": "Test channel"}, "from": h._from(),
            "date": int(datetime.now().timestamp()),
            "old_chat_member": {"status": "member", "user": {"id": BOT_ID, "is_bot": True, "first_name": "Bot"}},
            "new_chat_member": {"status": status, "user": {"id": BOT_ID, "is_bot": True, "first_name": "Bot"}},
        }}
    await h.feed(**bot_status("left"))
    h.session.clear()
    await h.click(Pj(a="list"))
    assert Pj(a="ch", c=c).pack() not in buttons()
    assert (await h.db(lambda s: s.get(Channel, c))).is_active is False

    # Rights back → the same project returns
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    h.session.clear()
    await h.click(Pj(a="list"))
    assert Pj(a="ch", c=c).pack() in buttons()

    # Disconnect → the channel is deleted from the bot and gone from the list
    await h.click(Pj(a="off", c=c))
    h.session.clear()
    await h.click(Pj(a="offok", c=c))
    assert await h.db(lambda s: s.get(Channel, c)) is None
    assert Pj(a="ch", c=c).pack() not in buttons()

    # Connecting it again starts from scratch but doesn't hand out a fresh trial
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    again = await h.db(lambda s: s.scalar(select(Channel)))
    assert again.trial_ends_at == trial_ends_at


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

    # the subscription screen opens the billing Mini App instead of old card/bank-transfer checkouts
    h.session.clear()
    await h.text("/subscribe")
    sent = next(m for n, m in h.session.calls if n == "SendMessage")
    buttons = [b for row in sent.reply_markup.inline_keyboard for b in row]
    assert [b.web_app.url for b in buttons if b.web_app] == ["https://flowpost.test/app/"]
    assert not any(b.url for b in buttons)

    # trials over → the channel falls back to the free plan, so publishing keeps working
    async def expire(s):
        u = await s.scalar(select(User).where(User.tg_id == USER_ID))
        u.trial_ends_at = utcnow() - timedelta(minutes=1)
        await s.execute(update(Channel).values(trial_ends_at=utcnow() - timedelta(minutes=1)))
        await s.commit()
    await h.db(expire)
    await h.text("Пост на безкоштовному тарифі")
    p = (await _post(h)).id
    await h.click(Ed(a="pub", p=p))
    await h.click(Ed(a="pubok", p=p))
    assert await h.db(lambda s: s.scalar(select(Publication).where(Publication.status == "published")))

    # LiqPay payment: server-to-server callback activates the subscription
    user = await _user(h)
    payload = {"status": "success", "order_id": f"flowpost-{user.id}-abc", "payment_id": "charge-1",
               "amount": 5, "currency": "USD"}
    await process_liqpay_payload(payload, h.sm, None)
    sub = await h.db(lambda s: s.scalar(select(Subscription)))
    assert sub.provider == "liqpay" and sub.current_period_end > utcnow()


async def test_stars_topup_pre_checkout_and_payment(h: Harness):
    await h.text("/start")
    user = await _user(h)
    payload = make_payload(user.id, 34)

    async def pre_checkout(amount: int, uid: int = USER_ID):
        h.session.clear()
        await h.feed(pre_checkout_query={"id": "pcq", "from": h._from(uid), "currency": "XTR",
                                         "total_amount": amount, "invoice_payload": payload})
        return next(m for n, m in h.session.calls if n == "AnswerPreCheckoutQuery")

    assert (await pre_checkout(34)).ok is True
    assert (await pre_checkout(35)).ok is False
    assert (await pre_checkout(34, uid=ADMIN_ID)).ok is False

    paid = {"currency": "XTR", "total_amount": 34, "invoice_payload": payload,
            "telegram_payment_charge_id": "tg-charge-1", "provider_payment_charge_id": ""}
    h.session.clear()
    await h.feed(message=h._message(successful_payment=paid))
    await h.feed(message=h._message(successful_payment=paid))
    user = await _user(h)
    assert (user.balance, user.cashback) == (34, 1)
    assert h.session.names().count("SendMessage") == 1 and "34 ⭐" in h.session.texts()


async def test_publish_is_paywalled_when_a_channel_has_no_plan(sessionmaker):
    settings = Settings(bot_token="123456:TEST", liqpay_enabled=False, free_posts_per_day=0, _env_file=None)
    session = MockSession()
    bot = Bot("123456:TEST", session=session, default=DefaultBotProperties(parse_mode="HTML"))
    dp = build_dispatcher(settings, sessionmaker, MemoryStorage())
    dp.workflow_data.update(settings=settings, publisher=Publisher(bot, None),
                            worker=Worker(bot, sessionmaker, Publisher(bot, None), settings), ai=AIService(settings))
    h = Harness(dp, bot, session, sessionmaker)
    try:
        await h.text("/start")
        await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))

        async def expire_channel_trial(s):
            await s.execute(update(Channel).values(trial_ends_at=utcnow() - timedelta(minutes=1)))
            await s.commit()
        await h.db(expire_channel_trial)
        await h.text("Пост без тарифу")
        p = (await _post(h)).id
        h.session.clear()
        await h.click(Ed(a="pubok", p=p))
        assert any(n == "AnswerCallbackQuery" and m.show_alert for n, m in h.session.calls)
        assert await h.db(lambda s: s.scalar(select(Publication))) is None
    finally:
        for router in dp.sub_routers:
            router._parent_router = None


async def test_settings_pay_button_opens_billing_mini_app(h: Harness):
    await h.text("/start")
    h.session.clear()
    await h.text("/settings")
    sent = next(m for n, m in h.session.calls if n == "SendMessage")
    web_apps = [b.web_app.url for row in sent.reply_markup.inline_keyboard for b in row if b.web_app]
    assert web_apps == ["https://flowpost.test/app/"]

    # a legacy «Оплатити підписку» callback from an old message points to the Mini App as well
    h.session.clear()
    await h.click(Bl(a="open"))
    sent = next(m for n, m in h.session.calls if n == "SendMessage")
    assert sent.reply_markup.inline_keyboard[0][0].web_app.url == "https://flowpost.test/app/"


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


async def _seed_second_channel(h: Harness, owner_id: int) -> int:
    async def create(session):
        channel = Channel(owner_id=owner_id, chat_id=CHANNEL_CHAT - 1, kind="channel", title="Другий канал",
                          username="testchan2", watermark={})
        session.add(channel)
        await session.commit()
        return channel.id
    return await h.db(create)


async def test_content_plan_and_edit_post_ask_for_channel_when_more_than_one(h: Harness):
    channel_id, _ = await _seed_published(h, message_id=4242)
    user = await _user(h)
    channel2_id = await _seed_second_channel(h, user.id)

    h.session.clear()
    await h.text("🗓 Контент-план")
    assert "Оберіть канал" in h.session.texts()
    kb_text = str(h.session.calls[-1][1].reply_markup)
    assert "Test Channel" in kb_text and "Другий канал" in kb_text

    h.session.clear()
    await h.click(Cp(a="day", c=channel_id))
    assert "Оберіть канал" not in h.session.texts()
    assert "Заплановано" in h.session.texts() or "нічого не заплановано" in h.session.texts()
    # the plan for channel 1 offers a way back to the channel picker
    kb_text = str(h.session.calls[-1][1].reply_markup)
    assert "Інший канал" in kb_text

    h.session.clear()
    await h.text("/edit")
    assert "Оберіть канал" in h.session.texts()
    kb_text = str(h.session.calls[-1][1].reply_markup)
    assert "Test Channel" in kb_text and "Другий канал" in kb_text

    h.session.clear()
    await h.click(Ep(a="pick", c=channel2_id))
    assert "Оберіть канал" not in h.session.texts()
    # channel 2 has no posts of its own
    assert "ще немає" in h.session.texts()


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


async def test_folders_group_channels_in_the_new_post_picker(h: Harness):
    channel_id, _ = await _seed_published(h, message_id=4242)
    user = await _user(h)
    channel2_id = await _seed_second_channel(h, user.id)

    # Налаштування → Інтерфейс → Папки → нова папка
    h.session.clear()
    await h.click(St(a="ui"))
    assert "Інтерфейс" in h.session.texts()
    await h.click(St(a="ui_folders"))
    await h.click(Fd(a="new"))
    h.session.clear()
    await h.text("Новини")
    folder = await h.db(lambda s: s.scalar(select(ChannelFolder)))
    assert folder.title == "Новини" and "створено" in h.session.texts()

    # tick one channel, save it into the folder
    h.session.clear()
    await h.click(Fd(a="tog", f=folder.id, c=channel_id))
    assert "Зберегти" in str(h.session.calls[-1][1].reply_markup)
    await h.click(Fd(a="save", f=folder.id))
    async def member_ids(s):
        return list(await s.scalars(select(ChannelFolderItem.channel_id)))
    members = await h.db(member_ids)
    assert members == [channel_id]

    # a new post now offers the folder plus the channel left outside it
    h.session.clear()
    await h.photo()
    post = await _post(h)
    kb_text = str(h.session.calls[-1][1].reply_markup)
    assert "Новини (1)" in kb_text and "Другий канал" in kb_text and "Test Channel" not in kb_text

    # entering the folder narrows the picker to its channels
    h.session.clear()
    await h.click(Fd(a="pick", f=folder.id, p=post.id))
    kb_text = str(h.session.calls[-1][1].reply_markup)
    assert "Test Channel" in kb_text and "Другий канал" not in kb_text
    assert "Вийти з папки" in kb_text

    # picking a channel there opens the editor for it
    h.session.clear()
    await h.click(Nc(c=channel_id, p=post.id))
    assert [t.channel_id for t in (await _post(h)).targets] == [channel_id]

    # folder settings: icon from the grid, a colour style, and a typed name
    h.session.clear()
    await h.click(Fd(a="set", f=folder.id))
    assert "Налаштування папки" in h.session.texts()
    await h.click(Fd(a="ico", f=folder.id, v="📍"))
    await h.click(Fd(a="sty", f=folder.id, v="success"))
    await h.text("Місто")
    await h.text("⚽")
    folder = await h.db(lambda s: s.scalar(select(ChannelFolder)))
    assert (folder.icon, folder.style, folder.title) == ("⚽", "success", "Місто")

    # the styled folder row carries icon, name and style into the post picker
    h.session.clear()
    await h.photo()
    row = (await _post(h)) and h.session.calls[-1][1].reply_markup.inline_keyboard[0][0]
    assert row.text == "⚽ Місто (1)" and row.style == "success"

    # deleting the folder keeps the channels themselves
    await h.click(Fd(a="delok", f=folder.id))
    assert await h.db(lambda s: s.scalar(select(ChannelFolder))) is None
    async def all_channels(s):
        return list(await s.scalars(select(Channel)))
    assert len(await h.db(all_channels)) == 2
    assert channel2_id


async def test_channel_list_order_and_paging(h: Harness):
    await _seed_published(h, message_id=4242)
    user = await _user(h)

    async def more(session):
        ids = []
        for i in range(5):
            channel = Channel(owner_id=user.id, chat_id=CHANNEL_CHAT - 10 - i, kind="channel",
                              title=f"Канал {i}", username=f"c{i}", watermark={})
            session.add(channel)
            await session.flush()
            ids.append(channel.id)
        await session.commit()
        return ids
    extra = await h.db(more)

    # Інтерфейс → Канали: four per page
    h.session.clear()
    await h.click(St(a="ui_channels"))
    assert "списку каналів" in h.session.texts()
    await h.click(St(a="ui_pp"))
    await h.click(St(a="ui_ppset", v="4"))
    assert (await _user(h)).channels_per_page == 4

    # pin the last channel to the front of every channel list
    h.session.clear()
    await h.click(St(a="ui_order"))
    await h.click(St(a="ui_ord", v=str(extra[-1])))
    assert (await _user(h)).channel_order == [extra[-1]]
    assert "1. " in str(h.session.calls[-1][1].reply_markup)

    # the new-post picker honours both: pinned channel first, four rows plus a page nav
    h.session.clear()
    await h.photo()
    rows = h.session.calls[-1][1].reply_markup.inline_keyboard
    assert rows[0][0].text.endswith("Канал 4")
    assert len(rows) == 5 and [b.text for b in rows[-1]] == ["·", "1/2", "▶️"]

    h.session.clear()
    post = await _post(h)
    await h.click(Fd(a="pick", p=post.id, pg=1))
    rows = h.session.calls[-1][1].reply_markup.inline_keyboard
    assert len(rows) == 3 and [b.text for b in rows[-1]] == ["◀️", "2/2", "·"]


async def test_support_message_is_forwarded_to_admins(h: Harness, settings: Settings):
    await h.text("/start")
    settings.admin_ids = str(ADMIN_ID)

    h.session.clear()
    await h.click(St(a="support"))
    assert "передам його команді" in h.session.texts()

    h.session.clear()
    await h.text("У мене проблема з оплатою")
    # without a support group the admin gets a header with the user's id and a copy of their message
    sent = [c for name, c in h.session.calls if name == "SendMessage"]
    admin_call = next(c for c in sent if getattr(c, "chat_id", None) == ADMIN_ID)
    assert str(USER_ID) in admin_call.text
    copy = next(c for name, c in h.session.calls if name == "CopyMessages")
    assert copy.chat_id == ADMIN_ID and copy.from_chat_id == USER_ID
    assert "надіслано" in h.session.texts()

    # no new post was created out of the support message
    async def count_posts(s):
        return len((await s.scalars(select(Post))).all())
    assert await h.db(count_posts) == 0


async def _support_topic(h: Harness) -> int:
    return (await h.db(lambda s: s.scalar(select(SupportThread)))).topic_id


async def test_support_group_gives_each_user_a_topic_and_relays_team_replies(h: Harness, settings: Settings):
    settings.support_chat_id = SUPPORT_CHAT
    await h.text("/start")

    # the first message opens a topic named after the user, with a card about them, and lands in it
    await h.click(St(a="support"))
    h.session.clear()
    await h.text("Не публікується пост")
    created = next(m for name, m in h.session.calls if name == "CreateForumTopic")
    assert created.chat_id == SUPPORT_CHAT and str(USER_ID) in created.name and "Олена" in created.name
    topic = await _support_topic(h)
    card = next(m for name, m in h.session.calls if name == "SendMessage" and m.chat_id == SUPPORT_CHAT)
    assert card.message_thread_id == topic and str(USER_ID) in card.text
    copy = next(m for name, m in h.session.calls if name == "CopyMessage")
    assert (copy.chat_id, copy.from_chat_id, copy.message_thread_id) == (SUPPORT_CHAT, USER_ID, topic)
    assert "надіслано" in h.session.texts()

    # a later message goes into the same topic
    await h.click(St(a="support"))
    h.session.clear()
    await h.photo()
    assert "CreateForumTopic" not in h.session.names()
    assert next(m for name, m in h.session.calls if name == "CopyMessage").message_thread_id == topic

    # the team's reply in the topic reaches the user from the bot, with a button to answer back
    h.session.clear()
    await h.in_topic(topic, text="Перевірте, чи бот адмін у каналі")
    answer = next(m for name, m in h.session.calls if name == "SendMessage" and m.chat_id == USER_ID)
    assert "Відповідь підтримки" in answer.text and "бот адмін" in answer.text
    assert answer.reply_markup.inline_keyboard[0][0].callback_data == St(a="support", v="reply").pack()
    assert "SetMessageReaction" in h.session.names()

    # a photo reply is copied with the header in its caption
    h.session.clear()
    await h.in_topic(topic, photo=[{"file_id": "shot", "file_unique_id": "shot", "width": 10, "height": 10}],
                     caption="Ось де налаштування")
    copied = next(m for name, m in h.session.calls if name == "CopyMessage")
    assert copied.chat_id == USER_ID and "Відповідь підтримки" in copied.caption and "налаштування" in copied.caption

    # «/...» is a note for the team and stays in the group
    h.session.clear()
    await h.in_topic(topic, text="/note користувач на пробному періоді")
    assert not [m for _, m in h.session.calls if getattr(m, "chat_id", None) == USER_ID]

    # the user answers back through the button
    h.session.clear()
    await h.click(St(a="support", v="reply"))
    assert "Напишіть відповідь" in h.session.texts()
    await h.text("Дякую, допомогло")
    assert next(m for name, m in h.session.calls if name == "CopyMessage").message_thread_id == topic

    # /stats counts who wrote to support and who is still waiting for a reply
    settings.admin_ids = str(ADMIN_ID)
    h.session.clear()
    await h.text("/stats", uid=ADMIN_ID)
    assert "Support: 1 users (active 7d: 1), awaiting reply: 1" in h.session.texts()
    await h.in_topic(topic, text="Радий допомогти!")
    h.session.clear()
    await h.text("/stats", uid=ADMIN_ID)
    assert "awaiting reply: 0" in h.session.texts()

    async def count_posts(s):
        return len((await s.scalars(select(Post))).all())
    assert await h.db(count_posts) == 0


async def test_support_topic_is_recreated_when_deleted_and_blocked_users_are_reported(h: Harness, settings: Settings):
    settings.support_chat_id = SUPPORT_CHAT
    await h.text("/start")
    await h.click(St(a="support"))
    await h.text("Питання")
    old_topic = await _support_topic(h)

    # the team deleted the topic: the next message opens a new one instead of getting lost
    h.session.errors["CopyMessage"] = [TelegramBadRequest(method=None, message="Bad Request: message thread not found")]
    await h.click(St(a="support"))
    h.session.clear()
    await h.text("Ще питання")
    new_topic = await _support_topic(h)
    assert new_topic != old_topic and "CreateForumTopic" in h.session.names()
    assert [m.message_thread_id for name, m in h.session.calls if name == "CopyMessage"][-1] == new_topic
    assert "надіслано" in h.session.texts()

    # the user blocked the bot: the team is told the reply didn't arrive
    h.session.errors["SendMessage"] = [TelegramForbiddenError(method=None, message="Forbidden: bot was blocked by the user")]
    h.session.clear()
    await h.in_topic(new_topic, text="Відповідь")
    assert "заблокував" in h.session.texts()

    # a topic nobody is attached to
    h.session.clear()
    await h.in_topic(424242, text="Привіт")
    assert "не пов'язана" in h.session.texts()


async def test_restart_clears_a_stuck_state_and_returns_the_keyboard(h: Harness, settings: Settings):
    await h.text("/start")
    settings.admin_ids = str(ADMIN_ID)
    await h.click(St(a="support"))  # now waiting for a support message

    h.session.clear()
    await h.text("/restart")
    sent = [c for name, c in h.session.calls if name == "SendMessage"][-1]
    assert type(sent.reply_markup).__name__ == "ReplyKeyboardMarkup"

    # the next message is no longer swallowed by the support flow
    h.session.clear()
    await h.text("Текст майбутнього поста")
    assert not [c for name, c in h.session.calls if name == "SendMessage" and getattr(c, "chat_id", None) == ADMIN_ID]
    assert t("post.no_channels", locale="uk") in h.session.texts()  # it reached the new-post flow


async def test_scheduling_offers_to_save_the_posts_settings_as_channel_defaults(h: Harness):
    await h.text("/start")
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    c = (await h.db(lambda s: s.scalar(select(Channel)))).id

    # a post with its own buttons and a couple of settings changed
    await h.text("Безкоштовний майстер-клас у Дніпрі")
    p = (await _post(h)).id
    await h.click(Ed(a="btn", p=p))
    await h.click(Ed(a="btn_set", p=p))
    await h.text("Реєстрація — https://t.me/testchan")
    await h.click(Ed(a="more", p=p))
    await h.click(Ed(a="mo_t", p=p, v="silent"))
    await h.click(Ed(a="mo_t", p=p, v="link_preview"))

    tomorrow = local_now("Europe/Kyiv").date() + timedelta(days=1)
    await h.click(Ed(a="sch", p=p))
    await h.click(Ed(a="slot", p=p, v=f"{tomorrow.toordinal()}_0930"))
    h.session.clear()
    await h.click(Ed(a="schok", p=p, v=f"{tomorrow.toordinal()}_0930"))

    # the «Готово» confirmation names the post, the full date and the channel, and offers the button
    done = [m for name, m in h.session.calls if name in ("SendMessage", "EditMessageText")][-1]
    assert "Готово" in done.text and "Безкоштовний майстер-клас" in done.text
    assert f"{tomorrow.day} вересня {tomorrow.year}, 09:30" in done.text
    assert done.reply_markup.inline_keyboard[0][0].text == t("ed.def_btn", locale="uk")

    # «Зберегти форматування та налаштування» → confirmation → saved onto the channel
    h.session.clear()
    await h.click(Ed(a="defs", p=p))
    assert "за замовчуванням" in h.session.texts()
    await h.click(Ed(a="defsx", p=p))  # ← Назад returns to the «Готово» screen
    assert "Готово" in h.session.texts()
    assert (await h.db(lambda s: s.get(Channel, c))).post_defaults == {}

    await h.click(Ed(a="defs", p=p))
    await h.click(Ed(a="defsok", p=p))
    channel = await h.db(lambda s: s.get(Channel, c))
    assert channel.post_defaults["options"]["silent"] is True
    assert channel.post_defaults["options"]["link_preview"] is False
    assert channel.post_defaults["buttons"] == [[{"text": "Реєстрація", "url": "https://t.me/testchan"}]]
    assert "ad_label" not in channel.post_defaults["options"]

    # the next post in that channel opens with those settings and buttons already applied
    await h.text("Наступний пост")
    new_post = await _post(h)
    assert new_post.id != p
    assert new_post.options["silent"] is True and new_post.options["link_preview"] is False
    assert new_post.parts[0].buttons == [[{"text": "Реєстрація", "url": "https://t.me/testchan"}]]


async def test_publishing_now_shows_the_same_done_screen_with_the_defaults_button(h: Harness):
    await h.text("/start")
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    c = (await h.db(lambda s: s.scalar(select(Channel)))).id

    await h.text("Безкоштовний майстер-клас у Дніпрі")
    p = (await _post(h)).id
    await h.click(Ed(a="more", p=p))
    await h.click(Ed(a="mo_t", p=p, v="silent"))

    await h.click(Ed(a="pub", p=p))
    h.session.clear()
    await h.click(Ed(a="pubok", p=p))

    done = [m for name, m in h.session.calls if name in ("SendMessage", "EditMessageText")][-1]
    assert "Готово" in done.text and "Безкоштовний майстер-клас" in done.text
    assert "опубліковано" in done.text
    # the channel name links straight to the published message, not to the channel
    published = await h.db(lambda s: s.scalar(select(Publication).where(Publication.status == "published")))
    assert f"/{published.message_ids['parts'][0]['ids'][0]}" in done.text
    assert done.reply_markup.inline_keyboard[0][0].text == t("ed.def_btn", locale="uk")

    # the same button saves the defaults from an already-published post
    await h.click(Ed(a="defs", p=p))
    await h.click(Ed(a="defsok", p=p))
    assert (await h.db(lambda s: s.get(Channel, c))).post_defaults["options"]["silent"] is True


async def test_a_failed_publication_keeps_the_detailed_report(h: Harness, monkeypatch):
    await h.text("/start")
    await h.feed(message=h._message(chat_shared={"request_id": 1, "chat_id": CHANNEL_CHAT}))
    await h.text("Пост, який не вийде")
    p = (await _post(h)).id

    from flowpost.services import worker as worker_mod
    from flowpost.services.delivery import DeliveryError

    async def boom(*args, **kwargs):
        raise DeliveryError("err.telegram")
    # the worker imported the function by name, so it has to be patched where it is used
    monkeypatch.setattr(worker_mod, "deliver_publication", boom)

    await h.click(Ed(a="pub", p=p))
    h.session.clear()
    await h.click(Ed(a="pubok", p=p))
    done = [m for name, m in h.session.calls if name in ("SendMessage", "EditMessageText")][-1]
    assert t("pub.result_title", locale="uk") in done.text
    assert done.reply_markup is None


async def test_admin_stats_count_channels_and_groups_apart(h: Harness):
    await h.text("/start")
    user = await _user(h)

    async def add(s):
        s.add_all([
            Channel(owner_id=user.id, chat_id=CHANNEL_CHAT, kind="channel", title="Канал",
                    discussion_chat_id=DISCUSSION_CHAT),
            Channel(owner_id=user.id, chat_id=DISCUSSION_CHAT, kind="group", title="Коментарі"),
            Channel(owner_id=user.id, chat_id=-1002, kind="group", title="Група для постів"),
            Channel(owner_id=user.id, chat_id=-1001, kind="channel", title="Відключений", is_active=False),
        ])
        await s.commit()
    await h.db(add)

    s = await h.db(lambda session: stats_repo.admin_stats(session, utcnow(), h.dp.workflow_data["settings"]))
    assert (s["channels_active"], s["groups_active"]) == (1, 1)  # the comments group isn't counted


async def test_admin_chats_lists_channels_with_links_and_groups(h: Harness, settings: Settings):
    await h.text("/start")
    user = await _user(h)

    async def add(s):
        s.add_all([
            Channel(owner_id=user.id, chat_id=CHANNEL_CHAT, kind="channel", title="Новини <Дніпра>",
                    username="dnipro_news", discussion_chat_id=DISCUSSION_CHAT),
            Channel(owner_id=user.id, chat_id=-1003, kind="channel", title="Закритий канал"),
            Channel(owner_id=user.id, chat_id=DISCUSSION_CHAT, kind="group", title="Коментарі"),
            Channel(owner_id=user.id, chat_id=-1002, kind="group", title="Чат району"),
            Channel(owner_id=user.id, chat_id=-1001, kind="channel", title="Відключений", is_active=False),
        ])
        await s.commit()
    await h.db(add)

    settings.admin_ids = str(ADMIN_ID)
    h.session.clear()
    await h.text("/chats", uid=ADMIN_ID)
    text = h.session.texts()
    assert "Channels (2)" in text and "Groups (1)" in text
    assert '<a href="https://t.me/dnipro_news">Новини &lt;Дніпра&gt;</a>' in text
    assert "Закритий канал (private)" in text and "Чат району" in text
    assert "Коментарі" not in text and "Відключений" not in text

    # not an admin → the command isn't there
    h.session.clear()
    await h.text("/chats")
    assert "Channels (" not in h.session.texts()


async def test_admin_broadcast_copies_the_message_to_the_chosen_audience(h: Harness, settings: Settings, monkeypatch):
    from flowpost.bot.callbacks import Bc
    from flowpost.bot.handlers import admin as admin_handlers
    monkeypatch.setattr(admin_handlers, "BROADCAST_DELAY", 0)
    await h.text("/start")                 # channel owner
    await h.text("/start", uid=999)        # no channels
    await h.text("/start", uid=555)        # owns a channel but blocks the bot
    await h.text("/start", uid=444)        # an admin the owner added to their channel
    owner, blocker, co_admin = await _user(h), *[
        await h.db(lambda s, uid=uid: s.scalar(select(User).where(User.tg_id == uid))) for uid in (555, 444)
    ]

    async def add(s):
        channel = Channel(owner_id=owner.id, chat_id=CHANNEL_CHAT, kind="channel", title="Новини")
        s.add_all([channel, Channel(owner_id=blocker.id, chat_id=-1003, kind="channel", title="Інший")])
        await s.flush()
        s.add(ChannelAdmin(channel_id=channel.id, user_id=co_admin.id))
        await s.commit()
    await h.db(add)

    # not an admin → nothing happens
    h.session.clear()
    await h.text("/broadcast")
    assert "Розсилка" not in h.session.texts()

    settings.admin_ids = str(ADMIN_ID)
    await h.text("/broadcast", uid=ADMIN_ID)
    await h.text("Оновлення: <b>нова функція</b>", uid=ADMIN_ID)
    kb = next(m for name, m in h.session.calls if name == "SendMessage" and "Кому надіслати" in m.text).reply_markup
    labels = [row[0].text for row in kb.inline_keyboard]
    # owners: 777 and 555; plus their admins: 444; without channels: 999 and the admin, who is a bot user too
    assert [label[-3:] for label in labels[:4]] == ["(2)", "(3)", "(2)", "(5)"]

    # the first recipient (the owner) has blocked the bot: marked as blocked, the rest still get it
    h.session.clear()
    h.session.errors["CopyMessage"] = [TelegramForbiddenError(method=None, message="blocked")]
    await h.click(Bc(a="send", v="channels"), uid=ADMIN_ID)
    assert [m.chat_id for name, m in h.session.calls if name == "CopyMessage"] == [USER_ID, 555, 444]
    text = h.session.texts()
    assert "Розсилку завершено" in text and "Доставлено: 2 / 3" in text and "Заблокували бота: 1" in text
    assert (await _user(h)).is_blocked

    # pressing the button again doesn't send it twice
    h.session.clear()
    await h.click(Bc(a="send", v="channels"), uid=ADMIN_ID)
    assert "CopyMessage" not in h.session.names()

    # those who haven't connected a channel yet
    await h.text("/broadcast", uid=ADMIN_ID)
    await h.text("Підключіть свій перший канал 👇", uid=ADMIN_ID)
    h.session.clear()
    await h.click(Bc(a="send", v="nochannels"), uid=ADMIN_ID)
    assert [m.chat_id for name, m in h.session.calls if name == "CopyMessage"] == [999, ADMIN_ID]

    # only the owners, without the admins they've added (777 has blocked the bot by now)
    await h.text("/broadcast", uid=ADMIN_ID)
    await h.text("Для власників каналів", uid=ADMIN_ID)
    h.session.clear()
    await h.click(Bc(a="send", v="owners"), uid=ADMIN_ID)
    assert [m.chat_id for name, m in h.session.calls if name == "CopyMessage"] == [555]
