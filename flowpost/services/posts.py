"""Pure helpers around post content: media items, grouping rules, signature and final text."""
from __future__ import annotations

import html

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from flowpost.db.models import Channel, Post, PostPart
from flowpost.i18n import t
from flowpost.services.html_sanitize import has_custom_emoji, visible_len
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
    "ad_label": False,
    "comments": True,
    "hidden_text": None,  # shown only to channel subscribers, behind a button under the post
}

MEDIA_ICONS = {"photo": "🖼", "video": "🎬", "animation": "🎞", "document": "📄", "audio": "🎵"}
WATERMARKABLE = {"photo", "video", "animation"}

# «Реклама» belongs to the /ad flow and a hidden text to its own post, so neither is carried over into other posts.
DEFAULTABLE_OPTIONS = tuple(k for k in DEFAULT_OPTIONS if k not in ("ad_label", "hidden_text"))
HIDDEN_PREFIX = "hx:"  # callback data of the «show hidden text» button: hx:<post id>
MAX_HIDDEN = 200  # Telegram's limit for the text of a callback alert


def options_of(post: Post) -> dict:
    return {**DEFAULT_OPTIONS, **(post.options or {})}


def post_defaults(post: Post) -> dict:
    """What «Зберегти форматування та налаштування» stores on a channel."""
    opts = options_of(post)
    buttons = post.parts[0].buttons if post.parts else []
    return {
        "options": {k: opts[k] for k in DEFAULTABLE_OPTIONS},
        "buttons": [list(row) for row in (buttons or [])],
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
    """Channel toggles, overridden by whatever «Зберегти форматування та налаштування» stored."""
    wm = wm_settings(channel.watermark)
    configured = wm_configured(channel.watermark)
    opts = {
        "signature": bool(channel.signature_on),
        "watermark": bool(wm.get("enabled")) and configured,
    }
    opts.update(channel_defaults(channel)["options"])
    # A saved default can't turn on a watermark the channel no longer has set up.
    opts["watermark"] = bool(opts["watermark"]) and configured
    if is_ad:
        opts.update({"signature": False, "ad_label": True, "auto_delete_hours": 24})
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


def render_signature(channel: Channel) -> str:
    template = channel.signature_template or default_signature_template(channel)
    link = f"https://t.me/{channel.username}" if channel.username else ""
    return (
        template.replace("{title}", html.escape(channel.title or ""))
        .replace("{link}", link)
        .replace("{username}", f"@{channel.username}" if channel.username else "")
    )


def final_text(part_text: str, opts: dict, channel: Channel | None, *, is_last: bool, lang: str) -> str:
    chunks = [part_text.strip()] if part_text and part_text.strip() else []
    if is_last and opts.get("ad_label"):
        chunks.append(f"<i>{html.escape(t('post.ad_label', locale=lang))}</i>")
    if is_last and opts.get("signature") and channel is not None:
        signature = render_signature(channel).strip()
        if signature:
            chunks.append(signature)
    return "\n\n".join(chunks)


def build_markup(buttons: list[list[dict]] | None) -> InlineKeyboardMarkup | None:
    """Link buttons ({"text", "url"}) and bot buttons ({"text", "callback"})."""
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=b["text"], callback_data=b["callback"]) if "callback" in b
            else InlineKeyboardButton(text=b["text"], url=b["url"])
            for b in row
        ]
        for row in buttons
    ])


def part_buttons(post: Post, idx: int, lang: str, *, hidden: bool = True) -> list[list[dict]]:
    """A part's buttons plus, under the last part, the «show hidden text» button when the post has one."""
    buttons = [list(row) for row in (post.parts[idx].buttons or [])]
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
    if len(part.media) > 1 and part.buttons:
        keys.append("warn.album_buttons")
    if part.media and text_len > CAPTION_LIMIT:
        keys.append("warn.long_caption")
    if text_len > TEXT_LIMIT:
        keys.append("warn.text_too_long")
    if not premium_emoji and has_custom_emoji(text):
        keys.append("warn.premium_emoji")
    return keys


def message_link(channel: Channel, message_id: int) -> str:
    return f"{channel_link(channel)}/{message_id}"
