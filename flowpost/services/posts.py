"""Pure helpers around post content: media items, grouping rules, signature and final text."""
from __future__ import annotations

import html

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from flowpost.db.models import Channel, Post, PostPart
from flowpost.i18n import t
from flowpost.services.html_sanitize import has_custom_emoji, visible_len
from flowpost.services.rich import carousel_ready
from flowpost.services.watermark import wm_configured, wm_settings

MAX_MEDIA = 10
CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096

DEFAULT_OPTIONS: dict = {
    "silent": False,
    "protect": False,
    "link_preview": True,
    "pin": False,
    "pin_hours": None,
    "auto_delete_hours": None,
    "watermark": False,
    "signature": True,
    "signature_tpl": 0,  # which of the channel's auto-signature templates goes under the post (see signature_templates)
    "comments": True,
    "hidden_text": None,  # shown only to channel subscribers, behind a button under the post
    "carousel": False,  # an album goes out as a slideshow to flip through (see services/rich.py)
    "spoiler": False,  # photos and videos come blurred until tapped
    "paid": False,  # photos and videos are unlocked for Stars (paid media)
    "paid_stars": 1,
    "ad_format": None,  # an ad's «1 / 24»-style format: a key of AD_FORMATS
    "ad_booking": False,  # a booked ad slot: it goes out only once the booking is confirmed
    "ad_advertiser": None,  # who booked the slot, when the ad itself isn't there yet
    "reply_to": None,  # {"ch": channel id, "msg": message id, "url": link}: the post goes out as a reply to it
    "ad_report": False,  # «📊 Звіт рекламодавцю»: the owner gets a report on how the ad ran (services/ads.py)
    "ad_check": None,  # the last «🛡 Перевірити рекламу»: {"hash": what was checked, "report": the AI verdict}
}

# An ad's format «top / feed»: no other post goes out in the channel for the first `top` hours,
# and the ad is deleted after `feed` hours.
AD_FORMATS: dict[int, tuple[int, int]] = {1: (1, 24), 2: (2, 48), 3: (3, 72)}

MEDIA_ICONS = {"photo": "🖼", "video": "🎬", "animation": "🎞", "document": "📄", "audio": "🎵"}
WATERMARKABLE = {"photo", "video", "animation"}
SPOILERABLE = {"photo", "video", "animation"}
PAID_TYPES = {"photo", "video"}
MAX_PAID_STARS = 25000  # Telegram's limit for paid media

# Ad settings and a hidden text belong to their own post, so none of them is carried over into other posts.
DEFAULTABLE_OPTIONS = tuple(
    k for k in DEFAULT_OPTIONS
    if k not in ("hidden_text", "paid", "paid_stars", "ad_format", "ad_booking", "ad_advertiser", "reply_to",
                 "ad_report", "ad_check")
)
HIDDEN_PREFIX = "hx:"  # callback data of the «show hidden text» button: hx:<post id>
GIVEAWAY_PREFIX = "gwj:"  # callback data of a giveaway's «Беру участь» button without the Mini App: gwj:<giveaway id>
HIDDEN_BTN_PREFIX = "hc:"  # callback data of a «Приховане продовження» button: hc:<post id>:<button id>
QUIZ_PREFIX = "qz:"  # callback data of a quiz answer button: qz:<post id>:<button id>
REACT_PREFIX = "rc:"  # callback data of a reaction button: rc:<post id>:<button id>
COMMENT_PREFIX = "cm:"  # «Залишити коментар» before the post is out and its link known: cm:<post id>
MAX_HIDDEN = 200  # Telegram's limit for the text of a callback alert
BUTTON_STYLES = ("primary", "success", "danger")  # Bot API 9.4 button colours: blue, green, red


def options_of(post: Post) -> dict:
    return {**DEFAULT_OPTIONS, **(post.options or {})}


def has_visual_media(media: list[dict]) -> bool:
    """Media the «Вигляд медіа» settings (spoiler, paid) can apply to."""
    return any(item.get("type") in SPOILERABLE for item in media)


def paid_ready(media: list[dict]) -> bool:
    """Telegram sells only photos and videos, up to 10 at a time."""
    return 0 < len(media) <= MAX_MEDIA and all(item.get("type") in PAID_TYPES for item in media)


def paid_stars(opts: dict, media: list[dict]) -> int | None:
    """The price of a part's media in Stars, or None when it goes out free."""
    if not opts.get("paid") or not paid_ready(media):
        return None
    return min(max(int(opts.get("paid_stars") or 1), 1), MAX_PAID_STARS)


def plain_buttons(rows: list[list[dict]] | None) -> list[list[dict]]:
    """The buttons the author types in as text — links and hints («Читати далі — текст») — without the other bot
    buttons (hidden continuations, quiz answers, reactions, giveaways)."""
    return [row for row in ([b for b in r if "url" in b or "hint" in b] for r in rows or []) if row]


def hidden_rows(rows: list[list[dict]] | None) -> list[list[dict]]:
    """«Приховане продовження» buttons: {"text", "hid", "hidden", "locked", "audience", "style"?}."""
    return [row for row in ([b for b in r if "hidden" in b] for r in rows or []) if row]


def quiz_rows(rows: list[list[dict]] | None) -> list[list[dict]]:
    """Quiz answer buttons: {"text", "hid", "quiz", "comment", "locked", "audience", "style"?}."""
    return [row for row in ([b for b in r if "quiz" in b] for r in rows or []) if row]


def bot_rows(rows: list[list[dict]] | None) -> list[list[dict]]:
    """The author's bot buttons — hidden continuations, quiz answers, reactions — in their order: the ones a typed
    list of link buttons doesn't replace."""
    return [row for row in ([b for b in r if BOT_KEYS & b.keys()] for r in rows or []) if row]


BOT_KEYS = {"hidden", "quiz", "react", "comment"}


def has_comment_button(rows: list[list[dict]] | None) -> bool:
    return any("comment" in b for row in rows or [] for b in row)


def comment_url(chat_id: int, username: str | None, message_id: int) -> str | None:
    """The link that opens the comments under a channel post: public by username, t.me/c for members otherwise."""
    if username:
        return f"https://t.me/{username}/{message_id}?comment=1"
    raw = str(chat_id)
    return f"https://t.me/c/{raw[4:]}/{message_id}?comment=1" if raw.startswith("-100") else None


def react_rows(rows: list[list[dict]] | None) -> list[list[dict]]:
    """Reaction buttons: {"text", "hid", "react", "style"?}; a tap counts one reaction per person."""
    return [row for row in ([b for b in r if "react" in b] for r in rows or []) if row]


def find_hidden(post: Post, hid: str) -> dict | None:
    """A hidden continuation or quiz answer button by its id."""
    return next((b for part in post.parts for row in part.buttons or [] for b in row if b.get("hid") == hid), None)


def quiz_locked_text(button: dict, lang: str | None = None) -> str:
    """What someone who may not answer a quiz sees: the author's text, or a nudge to subscribe (or boost)."""
    return button.get("locked") or t(f"qz.locked_{button.get('audience') or 'subs'}", locale=lang)


def quiz_answers(post: Post, quiz: str) -> list[dict]:
    return [b for part in post.parts for row in part.buttons or [] for b in row if b.get("quiz") == quiz]


def giveaway_rows(rows: list[list[dict]] | None) -> list[list[dict]]:
    return [row for row in ([b for b in r if "giveaway" in b] for r in rows or []) if row]


def post_defaults(post: Post) -> dict:
    """What «Зберегти форматування та налаштування» stores on a channel."""
    opts = options_of(post)
    buttons = post.parts[0].buttons if post.parts else []
    return {
        "options": {k: opts[k] for k in DEFAULTABLE_OPTIONS},
        "buttons": plain_buttons(buttons),
    }


def channel_defaults(channel: Channel) -> dict:
    """The stored defaults of `channel`, cleaned of anything a newer/older version wrote."""
    data = channel.post_defaults or {}
    options = data.get("options") or {}
    return {
        "options": {k: v for k, v in options.items() if k in DEFAULTABLE_OPTIONS},
        "buttons": [list(row) for row in (data.get("buttons") or [])],
    }


def initial_options(channel: Channel, is_ad: bool) -> dict:
    """Channel toggles, overridden by whatever «Зберегти форматування та налаштування» stored. An ad goes out as
    the advertiser sent it: without the channel's signature, watermark or saved formatting."""
    if is_ad:
        return {"signature": False, "watermark": False}
    wm = wm_settings(channel.watermark)
    configured = wm_configured(channel.watermark)
    opts = {
        "signature": bool(channel.signature_on),
        "watermark": bool(wm.get("enabled")) and configured,
    }
    opts.update(channel_defaults(channel)["options"])
    # A saved default can't turn on a watermark the channel no longer has set up.
    opts["watermark"] = bool(opts["watermark"]) and configured
    return opts


def media_from_message(m: Message) -> dict | None:
    if m.photo:
        p = m.photo[-1]
        return {"type": "photo", "file_id": p.file_id, "uid": p.file_unique_id, "size": p.file_size,
                "w": p.width, "h": p.height}
    if m.animation:  # must be checked before document: GIF messages carry both
        a = m.animation
        return {"type": "animation", "file_id": a.file_id, "uid": a.file_unique_id, "size": a.file_size,
                "w": a.width, "h": a.height}
    if m.video:
        v = m.video
        return {"type": "video", "file_id": v.file_id, "uid": v.file_unique_id, "size": v.file_size,
                "w": v.width, "h": v.height}
    if m.document:
        d = m.document
        return {"type": "document", "file_id": d.file_id, "uid": d.file_unique_id, "size": d.file_size,
                "name": d.file_name}
    if m.audio:
        au = m.audio
        return {"type": "audio", "file_id": au.file_id, "uid": au.file_unique_id, "size": au.file_size,
                "name": au.title or au.file_name}
    return None


def message_text(m: Message) -> str:
    """User text with formatting preserved as Telegram HTML."""
    if not (m.text or m.caption):
        return ""
    return m.html_text


def poll_from_message(m: Message) -> dict | None:
    """A native Telegram poll the admin composed and sent to the bot, as storable part data."""
    p = m.poll
    if p is None:
        return None
    data: dict = {
        "question": p.question,
        "options": [o.text for o in p.options],
        "is_anonymous": p.is_anonymous,
        "type": p.type,
        "allows_multiple_answers": p.allows_multiple_answers,
    }
    if p.type == "quiz" and p.correct_option_id is not None:
        data["correct_option_id"] = p.correct_option_id
    if p.explanation:
        data["explanation"] = p.explanation
    if p.open_period:  # relative duration in seconds; `close_date` is an absolute timestamp fixed at
        data["open_period"] = p.open_period  # compose time, so it's dropped — it would be stale by send time
    return data


def group_error(media: list[dict]) -> str | None:
    """Return an i18n key if these media items can't be sent together."""
    if len(media) > MAX_MEDIA:
        return "err.media_too_many"
    if len(media) <= 1:
        return None
    types = {item["type"] for item in media}
    if "animation" in types:
        return "err.media_gif_group"
    if "document" in types and types != {"document"}:
        return "err.media_mix_document"
    if "audio" in types and types != {"audio"}:
        return "err.media_mix_audio"
    return None


def media_icon(item: dict) -> str:
    return MEDIA_ICONS.get(item.get("type", ""), "📎")


def part_icon(part: PostPart) -> str:
    if part.poll:
        return "🎯" if part.poll.get("type") == "quiz" else "📊"
    if not part.media:
        return "📝"
    if len(part.media) > 1:
        return "🗂"
    return media_icon(part.media[0])


def part_preview_text(part: PostPart) -> str:
    """Plain-ish text to show in lists/previews — the poll question when this part is a poll."""
    if part.poll:
        return html.escape(part.poll.get("question", ""))
    return part.text_html


def default_signature_template(channel: Channel) -> str:
    return '<a href="{link}">{title}</a>' if channel.username else "<b>{title}</b>"


def channel_link(channel: Channel) -> str:
    """A t.me link that opens the channel — public @username, or the internal chat link for members."""
    if channel.username:
        return f"https://t.me/{channel.username}"
    internal = str(channel.chat_id)
    if internal.startswith("-100"):
        internal = internal[4:]
    return f"https://t.me/c/{internal.lstrip('-')}"


def channel_link_html(channel: Channel) -> str:
    """Channel title as a link to the channel."""
    title = html.escape(channel.title or "")
    return f'<a href="{channel_link(channel)}">{title}</a>'


def signature_templates(channel: Channel) -> list[tuple[int, str]]:
    """(id, template) of every auto-signature: 0 is the main one, then those added with «Додати шаблон»."""
    main = channel.signature_template or default_signature_template(channel)
    return [(0, main)] + [(int(x["id"]), x["html"]) for x in (channel.signature_extra or [])]


def render_signature(channel: Channel, template_id: int = 0) -> str:
    """The signature from template `template_id`; the main one when that template is gone (or the channel never had it)."""
    templates = dict(signature_templates(channel))
    template = templates.get(int(template_id or 0)) or templates[0]
    link = f"https://t.me/{channel.username}" if channel.username else ""
    return (
        template.replace("{title}", html.escape(channel.title or ""))
        .replace("{link}", link)
        .replace("{username}", f"@{channel.username}" if channel.username else "")
    )


def final_text(part_text: str, opts: dict, channel: Channel | None, *, is_last: bool, lang: str) -> str:
    chunks = [part_text.strip()] if part_text and part_text.strip() else []
    if is_last and opts.get("signature") and channel is not None:
        signature = render_signature(channel, opts.get("signature_tpl") or 0).strip()
        if signature:
            chunks.append(signature)
    return "\n\n".join(chunks)


def drop_signature(post: Post) -> bool:
    """Link buttons under a post take the place of the channel's auto-signature: it's switched off (the editor's
    «✍️ Автопідпис» turns it back on). True when it was on."""
    if not options_of(post)["signature"]:
        return False
    post.options = {**(post.options or {}), "signature": False}
    return True


def buttons_from_messages(messages: list) -> tuple[list[list[dict]], int]:
    """The link buttons of a sent or forwarded post, rows kept as they were, and how many buttons were left out:
    a bot's own buttons (callback, web app, …) only work in the bot that made them."""
    rows: list[list[dict]] = []
    skipped = 0
    markup = next((m.reply_markup for m in messages if getattr(m, "reply_markup", None)), None)
    for row in getattr(markup, "inline_keyboard", None) or []:
        kept = []
        for b in row:
            if b.url:
                kept.append({"text": b.text, "url": b.url, **({"style": b.style} if getattr(b, "style", None) else {})})
            else:
                skipped += 1
        if kept:
            rows.append(kept)
    return rows, skipped


def build_markup(buttons: list[list[dict]] | None) -> InlineKeyboardMarkup | None:
    """Link buttons ({"text", "url"}) and bot buttons ({"text", "callback"})."""
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=b["text"], callback_data=b["callback"], style=b.get("style")) if "callback" in b
            else InlineKeyboardButton(text=b["text"], url=b["url"], style=b.get("style"))
            for b in row
        ]
        for row in buttons
    ])


def part_buttons(
    post: Post, idx: int, lang: str, *, hidden: bool = True, comments: str | None = None,
) -> list[list[dict]]:
    """A part's buttons plus, under the last part, the «show hidden text» button when the post has one
    (`hidden=False` on the free plan leaves that one out). «Залишити коментар» links to `comments` (the post's
    comments) once it's out. Hidden continuations, quiz answers and reactions become bot buttons
    on every plan."""
    buttons = [
        [
            {"text": b["text"], "callback": f"{HIDDEN_BTN_PREFIX}{post.id}:{b['hid']}", "style": b.get("style")}
            if "hidden" in b or "hint" in b else
            {"text": b["text"], "callback": f"{QUIZ_PREFIX}{post.id}:{b['hid']}", "style": b.get("style")}
            if "quiz" in b else
            {"text": b["text"], "callback": f"{REACT_PREFIX}{post.id}:{b['hid']}", "style": b.get("style")}
            if "react" in b else
            ({"text": b["text"], "url": comments} if comments else {"text": b["text"], "callback": f"{COMMENT_PREFIX}{post.id}"})
            if "comment" in b else b
            for b in row
        ]
        for row in post.parts[idx].buttons or []
    ]
    if hidden and idx == len(post.parts) - 1 and options_of(post).get("hidden_text"):
        buttons.append([{"text": t("hidden.btn", locale=lang), "callback": f"{HIDDEN_PREFIX}{post.id}"}])
    return buttons


def part_is_empty(part: PostPart) -> bool:
    return not (part.media or (part.text_html or "").strip() or part.poll)


def post_is_empty(post: Post) -> bool:
    return all(part_is_empty(p) for p in post.parts)


def part_warnings(
    part: PostPart, opts: dict, channel: Channel | None, lang: str, *, is_last: bool, premium_emoji: bool = False,
) -> list[str]:
    if part.poll:
        return []
    keys: list[str] = []
    text = final_text(part.text_html, opts, channel, is_last=is_last, lang=lang)
    text_len = visible_len(text)
    paid = paid_stars(opts, part.media) is not None
    carousel = bool(opts.get("carousel")) and carousel_ready(part.media) and not paid
    if opts.get("paid") and part.media and not paid:
        keys.append("warn.paid_types")
    elif paid and channel is not None and channel.kind != "channel":
        keys.append("warn.paid_group")
    if len(part.media) > 1 and part.buttons and not carousel and not paid:
        keys.append("warn.album_buttons")
    if part.media and text_len > CAPTION_LIMIT and not carousel:
        keys.append("warn.long_caption")
    if text_len > TEXT_LIMIT:
        keys.append("warn.text_too_long")
    if not premium_emoji and has_custom_emoji(text):
        keys.append("warn.premium_emoji")
    return keys


def message_link(channel: Channel, message_id: int) -> str:
    return f"{channel_link(channel)}/{message_id}"
