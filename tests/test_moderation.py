from flowpost.services.moderation import (
    contains_banned_word,
    contains_spam_link,
    is_flood,
    moderation_settings,
    violation,
)


def test_moderation_settings_defaults_to_enabled_with_no_custom_words():
    assert moderation_settings(None) == {"enabled": True, "banned_words": []}
    assert moderation_settings({"enabled": False}) == {"enabled": False, "banned_words": []}


def test_contains_banned_word_matches_built_in_profanity():
    assert contains_banned_word("ти справжня сука!", [])
    assert not contains_banned_word("яка гарна днина сьогодні", [])


def test_contains_banned_word_ignores_evasive_punctuation():
    assert contains_banned_word("с.у.к.а", [])


def test_contains_banned_word_matches_custom_words():
    assert contains_banned_word("купи це зараз", ["купи"])
    assert not contains_banned_word("купи це зараз", ["продай"])


def test_contains_spam_link_detects_telegram_and_http_links():
    assert contains_spam_link("Заходь: t.me/some_channel")
    assert contains_spam_link("check https://example.com/promo")
    assert not contains_spam_link("Дуже дякую за пост!")


def test_contains_spam_link_detects_channel_mentions():
    assert contains_spam_link("підписуйся на @some_channel_promo")
    assert not contains_spam_link("дякую @bob")  # short mention, below the username length floor


def test_is_flood_detects_repeated_message_from_same_user():
    cache: dict = {}
    assert not is_flood(cache, chat_id=1, user_id=1, text="привіт", now=0.0)
    assert is_flood(cache, chat_id=1, user_id=1, text="привіт", now=1.0)


def test_is_flood_ignores_different_text_or_stale_repeats():
    cache: dict = {}
    is_flood(cache, chat_id=1, user_id=1, text="привіт", now=0.0)
    assert not is_flood(cache, chat_id=1, user_id=1, text="бувай", now=1.0)

    cache2: dict = {}
    is_flood(cache2, chat_id=1, user_id=1, text="привіт", now=0.0)
    assert not is_flood(cache2, chat_id=1, user_id=1, text="привіт", now=1000.0)


def test_violation_prioritizes_profanity_then_links_then_flood():
    cache: dict = {}
    assert violation("ти сука", [], cache, 1, 1) == "profanity"
    assert violation("t.me/spam", [], cache, 1, 1) == "spam_link"
    assert violation("клас!", [], cache, 1, 1) is None
    assert violation("клас!", [], cache, 1, 1) == "flood"
