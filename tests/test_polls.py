from types import SimpleNamespace

from flowpost.db.models import Post, PostPart, PostTarget
from flowpost.services.posts import part_icon, part_is_empty, part_preview_text, poll_from_message
from flowpost.services.publisher import Publisher, send_poll_part
from flowpost.services.publisher import SendOptions


def _poll_message(**overrides) -> SimpleNamespace:
    defaults = dict(
        question="Кава чи чай?",
        options=[SimpleNamespace(text="Кава"), SimpleNamespace(text="Чай")],
        is_anonymous=True,
        type="regular",
        allows_multiple_answers=False,
        correct_option_id=None,
        explanation=None,
        open_period=None,
        close_date=None,
    )
    return SimpleNamespace(poll=SimpleNamespace(**{**defaults, **overrides}))


def test_poll_from_message_extracts_regular_poll():
    data = poll_from_message(_poll_message())
    assert data == {
        "question": "Кава чи чай?", "options": ["Кава", "Чай"],
        "is_anonymous": True, "type": "regular", "allows_multiple_answers": False,
    }


def test_poll_from_message_keeps_quiz_answer_and_explanation():
    data = poll_from_message(_poll_message(type="quiz", correct_option_id=1, explanation="Бо чай смачніший"))
    assert data["correct_option_id"] == 1
    assert data["explanation"] == "Бо чай смачніший"


def test_poll_from_message_keeps_relative_open_period_drops_absolute_close_date():
    data = poll_from_message(_poll_message(open_period=300, close_date=1234567890))
    assert data["open_period"] == 300
    assert "close_date" not in data


def test_poll_from_message_returns_none_without_a_poll():
    assert poll_from_message(SimpleNamespace(poll=None)) is None


def test_poll_part_is_not_empty_and_uses_question_as_preview():
    part = PostPart(position=0, text_html="", media=[], buttons=[], poll={"question": "Кава чи чай?", "options": ["Кава", "Чай"]})
    assert not part_is_empty(part)
    assert part_icon(part) == "📊"
    assert part_preview_text(part) == "Кава чи чай?"


def test_quiz_part_gets_a_distinct_icon():
    part = PostPart(position=0, text_html="", media=[], buttons=[], poll={"question": "?", "options": ["A", "B"], "type": "quiz"})
    assert part_icon(part) == "🎯"


async def test_send_poll_part_calls_bot_send_poll(fake_bot):
    poll = {
        "question": "Кава чи чай?", "options": ["Кава", "Чай"], "is_anonymous": True,
        "type": "quiz", "correct_option_id": 0, "allows_multiple_answers": False,
    }
    sent = await send_poll_part(fake_bot, 1, poll, [[{"text": "Go", "url": "https://t.me/x"}]], SendOptions())
    name, chat, question, kw = fake_bot.calls[0]
    assert name == "send_poll" and chat == 1 and question == "Кава чи чай?"
    assert kw["options"] == ["Кава", "Чай"] and kw["type"] == "quiz" and kw["correct_option_id"] == 0
    assert kw["reply_markup"] is not None
    assert len(sent.ids) == 1
    assert sent.markup_msg == sent.ids[0]


async def test_publish_post_sends_poll_and_text_parts(fake_bot):
    post = Post(owner_id=1, options={"signature": False})
    post.parts = [
        PostPart(position=0, text_html="<b>Привіт</b>", media=[], buttons=[]),
        PostPart(position=1, text_html="", media=[], buttons=[], poll={"question": "Ну як?", "options": ["Добре", "Погано"]}),
    ]
    post.targets = [PostTarget(channel_id=1, position=0)]
    result = await Publisher(fake_bot).publish_post(post, None, "uk", chat_id=1)
    assert fake_bot.names() == ["send_message", "send_poll"]
    assert len(result.parts) == 2
