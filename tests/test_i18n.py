import re
from pathlib import Path

from flowpost.bot.setup import COMMANDS
from flowpost.i18n import detect_lang, en, t, uk, variants

SRC = Path(__file__).resolve().parents[1] / "flowpost"
PREFIXES = (
    "err|warn|ai|alb|save|notify|pay|addch|media|provider|cmd|bot|sch|ed|more|rep|parts|multi|plan|proj|set|sig|wm|"
    "topic|editp|fld|btn|btn_menu|media_menu|menu|start|help|post|pub|cancel|paywall|fmt"
)
KEY_RE = re.compile(r"[\"']((?:" + PREFIXES + r")\.[a-z0-9_]+)[\"']")
FILE_SUFFIXES = ("png", "jpg", "mp4", "db")


def used_keys() -> set[str]:
    keys: set[str] = set()
    for path in SRC.rglob("*.py"):
        if "i18n" in path.parts:
            continue
        keys.update(KEY_RE.findall(path.read_text(encoding="utf-8")))
    keys.update(f"media.{m}" for m in ("photo", "video", "animation", "document", "audio"))
    keys.update(f"provider.{p}" for p in ("stars", "liqpay", "manual"))
    keys.update(f"cmd.{c}" for c in COMMANDS)
    return {k for k in keys if k.rsplit(".", 1)[1] not in FILE_SUFFIXES}


def test_locales_have_same_keys():
    assert set(uk.TEXTS) == set(en.TEXTS), set(uk.TEXTS) ^ set(en.TEXTS)


def test_every_used_key_is_translated():
    missing = sorted(k for k in used_keys() if k not in uk.TEXTS)
    assert not missing, missing


def test_placeholders_match_between_languages():
    field = re.compile(r"(?<!\{)\{([a-z_]+)\}(?!\})")
    for key, uk_text in uk.TEXTS.items():
        assert set(field.findall(uk_text)) == set(field.findall(en.TEXTS[key])), key


def test_every_template_formats():
    for table in (uk.TEXTS, en.TEXTS):
        for key, text in table.items():
            names = set(re.findall(r"(?<!\{)\{([a-z_]+)\}(?!\})", text))
            text.format(**{n: "x" for n in names})  # must not raise


def test_limits_for_telegram_profile():
    for table in (uk.TEXTS, en.TEXTS):
        assert len(table["bot.description"]) <= 512
        assert len(table["bot.short_description"]) <= 120
        for c in COMMANDS:
            assert 1 <= len(table[f"cmd.{c}"]) <= 256


def test_t_and_variants():
    assert t("btn.create_post", locale="uk") != t("btn.create_post", locale="en")
    assert variants("btn.create_post") == {uk.TEXTS["btn.create_post"], en.TEXTS["btn.create_post"]}
    assert t("no.such.key") == "no.such.key"
    assert detect_lang("uk") == "uk" and detect_lang("ru") == "uk" and detect_lang("de") == "en"
