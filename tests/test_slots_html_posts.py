from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from flowpost.services.html_sanitize import sanitize_html, snippet, visible_len
from flowpost.services.posts import final_text, group_error, message_link, render_signature
from flowpost.services.slots import day_bounds_utc, fmt_date, generate_slots, to_utc


def test_fmt_date_matches_spec():
    assert fmt_date(date(2026, 9, 11), "uk") == "пт, 11 вер"
    assert fmt_date(date(2026, 9, 11), "en") == "Fri, 11 Sep"


def test_slots_today_start_from_next_five_minutes():
    now = datetime(2026, 9, 11, 10, 2, 30, tzinfo=ZoneInfo("Europe/Kyiv"))
    slots, more = generate_slots(date(2026, 9, 11), now)
    assert slots[:3] == [time(10, 5), time(10, 10), time(10, 15)]
    assert len(slots) == 12 and more


def test_slots_future_day_from_nine_and_paging():
    now = datetime(2026, 9, 11, 22, 0, tzinfo=ZoneInfo("Europe/Kyiv"))
    first, _ = generate_slots(date(2026, 9, 12), now)
    second, _ = generate_slots(date(2026, 9, 12), now, page=1)
    assert first[0] == time(9, 0) and first[-1] == time(9, 55)
    assert second[0] == time(10, 0)


def test_slots_late_evening_and_past_day():
    now = datetime(2026, 9, 11, 23, 58, tzinfo=ZoneInfo("Europe/Kyiv"))
    assert generate_slots(date(2026, 9, 11), now) == ([], False)
    assert generate_slots(date(2026, 9, 10), now) == ([], False)


def test_slots_include_favourite_times():
    """Frequently used off-grid times sit among the regular slots; today only while still ahead."""
    tomorrow = generate_slots(date(2026, 9, 12), datetime(2026, 9, 11, 22, 0), extra=[time(9, 2), time(7, 30)])[0]
    assert tomorrow[:4] == [time(7, 30), time(9, 0), time(9, 2), time(9, 5)]
    today = generate_slots(date(2026, 9, 11), datetime(2026, 9, 11, 10, 2), extra=[time(10, 2), time(10, 3)])[0]
    assert today[:2] == [time(10, 3), time(10, 5)]


def test_timezone_conversion():
    assert to_utc(date(2026, 9, 11), time(14, 35), "Europe/Kyiv") == datetime(2026, 9, 11, 11, 35, tzinfo=timezone.utc)
    start, end = day_bounds_utc(date(2026, 9, 11), "Europe/Kyiv")
    assert (end - start).total_seconds() == 86400


def test_sanitize_html():
    raw = "```html\n<h1>Заголовок</h1><p>Текст <strong>жирний</strong> <a href='javascript:x'>bad</a> <a href=\"https://t.me/x\">ok</a></p><ul><li>один</li></ul>\n```"
    out = sanitize_html(raw)
    assert "<b>Заголовок</b>" in out
    assert "<b>жирний</b>" in out
    assert "javascript" not in out and "bad" in out
    assert '<a href="https://t.me/x">ok</a>' in out
    assert "• один" in out
    assert sanitize_html("<b>unclosed <i>tags") == "<b>unclosed <i>tags</i></b>"
    assert sanitize_html("5 < 6 & 7") == "5 &lt; 6 &amp; 7"


def test_visible_len_and_snippet():
    assert visible_len("<b>Привіт</b> 👋") == len("Привіт ") + 2  # emoji is 2 UTF-16 units
    assert snippet("<b>" + "а" * 100 + "</b>", 10).endswith("…")


def _channel(**kw):
    base = dict(id=1, title="Діти в місті", username="dnipro_dityvmisti", signature_template=None, chat_id=-1001234567890)
    base.update(kw)
    return SimpleNamespace(**base)


def test_signature_and_final_text():
    ch = _channel()
    assert render_signature(ch) == '<a href="https://t.me/dnipro_dityvmisti">Діти в місті</a>'
    assert render_signature(_channel(username=None)) == "<b>Діти в місті</b>"
    assert render_signature(_channel(signature_template="👉 {username}")) == "👉 @dnipro_dityvmisti"
    text = final_text("Текст", {"signature": True, "ad_label": True}, ch, is_last=True, lang="uk")
    assert text.startswith("Текст\n\n<i>Реклама</i>\n\n<a href=")
    assert final_text("Текст", {"signature": True}, ch, is_last=False, lang="uk") == "Текст"


def test_group_rules():
    photo, video = {"type": "photo"}, {"type": "video"}
    assert group_error([photo, video]) is None
    assert group_error([photo, {"type": "animation"}]) == "err.media_gif_group"
    assert group_error([photo, {"type": "document"}]) == "err.media_mix_document"
    assert group_error([{"type": "audio"}, {"type": "audio"}]) is None
    assert group_error([photo] * 11) == "err.media_too_many"


def test_message_link():
    assert message_link(_channel(), 5) == "https://t.me/dnipro_dityvmisti/5"
    assert message_link(_channel(username=None), 5) == "https://t.me/c/1234567890/5"
