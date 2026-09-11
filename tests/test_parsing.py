from datetime import time

import pytest

from flowpost.services.parsing import ParseError, buttons_to_text, parse_buttons, parse_positive_int, parse_time, parse_topic


def test_parse_buttons_single_and_rows():
    rows = parse_buttons("Читати далі — https://t.me/nashe_misto\nСайт - example.com | Чат — t.me/chat")
    assert rows == [
        [{"text": "Читати далі", "url": "https://t.me/nashe_misto"}],
        [{"text": "Сайт", "url": "https://example.com"}, {"text": "Чат", "url": "https://t.me/chat"}],
    ]
    assert "Читати далі — https://t.me/nashe_misto" in buttons_to_text(rows)


@pytest.mark.parametrize("raw,key", [
    ("", "err.buttons_empty"),
    ("просто текст", "err.buttons_format"),
    ("Кнопка — not a url", "err.buttons_url"),
])
def test_parse_buttons_errors(raw, key):
    with pytest.raises(ParseError) as exc:
        parse_buttons(raw)
    assert exc.value.key == key


@pytest.mark.parametrize("raw,expected", [
    ("14:35", time(14, 35)), ("9:05", time(9, 5)), ("09.05", time(9, 5)), ("23 59", time(23, 59)), (" 0:00 ", time(0, 0)),
])
def test_parse_time_ok(raw, expected):
    assert parse_time(raw) == expected


@pytest.mark.parametrize("raw", ["24:00", "12:60", "1435", "abc", "", "12:5"])
def test_parse_time_bad(raw):
    with pytest.raises(ParseError) as exc:
        parse_time(raw)
    assert exc.value.key == "err.time_format"


def test_parse_positive_int():
    assert parse_positive_int("24", 720) == 24
    for bad in ("0", "-1", "721", "x"):
        with pytest.raises(ParseError):
            parse_positive_int(bad, 720)


def test_parse_topic():
    assert parse_topic("https://t.me/c/1234567/77").topic_id == 77
    assert parse_topic("t.me/mygroup/15/200").topic_id == 15
    assert parse_topic("42").topic_id == 42
    with pytest.raises(ParseError):
        parse_topic("hello")
