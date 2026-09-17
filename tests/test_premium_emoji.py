from types import SimpleNamespace

from aiogram.methods import SendMediaGroup, SendMessage
from aiogram.types import InputMediaPhoto, MessageEntity

from flowpost.bot.middlewares.premium_emoji import StripCustomEmojiMiddleware
from flowpost.services.html_sanitize import has_custom_emoji, strip_custom_emoji, visible_len
from flowpost.services.posts import part_warnings

PREMIUM = '<b>Хіт</b> <tg-emoji emoji-id="5368324170671202286">🔥</tg-emoji> дня'
PLAIN = "<b>Хіт</b> 🔥 дня"


def test_strip_keeps_the_fallback_emoji():
    assert strip_custom_emoji(PREMIUM) == PLAIN
    assert has_custom_emoji(PREMIUM) and not has_custom_emoji(PLAIN)
    # Telegram counts a custom emoji as its fallback, so stripping must not change the length we check.
    assert visible_len(PREMIUM) == visible_len(PLAIN)


async def _through(method):
    async def make_request(bot, m):
        return None

    await StripCustomEmojiMiddleware()(make_request, None, method)
    return method


async def test_middleware_strips_text_captions_and_entities():
    assert (await _through(SendMessage(chat_id=1, text=PREMIUM))).text == PLAIN

    group = await _through(SendMediaGroup(chat_id=1, media=[InputMediaPhoto(media="f", caption=PREMIUM)]))
    assert group.media[0].caption == PLAIN

    entities = [
        MessageEntity(type="custom_emoji", offset=0, length=2, custom_emoji_id="5368324170671202286"),
        MessageEntity(type="bold", offset=3, length=3),
    ]
    sent = await _through(SendMessage(chat_id=1, text="🔥 дня", entities=entities))
    assert [e.type for e in sent.entities] == ["bold"]


async def test_middleware_leaves_ordinary_messages_alone():
    sent = await _through(SendMessage(chat_id=1, text=PLAIN))
    assert sent.text == PLAIN and sent.entities is None


def _part(text: str) -> SimpleNamespace:
    return SimpleNamespace(poll=None, text_html=text, media=[], buttons=[])


def test_editor_warns_only_while_premium_emoji_is_off():
    part = _part(PREMIUM)
    assert part_warnings(part, {}, None, "uk", is_last=True) == ["warn.premium_emoji"]
    assert part_warnings(part, {}, None, "uk", is_last=True, premium_emoji=True) == []
    assert part_warnings(_part(PLAIN), {}, None, "uk", is_last=True) == []
