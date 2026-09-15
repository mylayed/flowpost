"""Builds and sends posts to Telegram (channels and preview chats)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.types import (
    BufferedInputFile,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    LinkPreviewOptions,
    Message,
)
from sqlalchemy.orm.attributes import flag_modified

from flowpost.db.models import Channel, Post
from flowpost.services.html_sanitize import visible_len
from flowpost.services.posts import CAPTION_LIMIT, WATERMARKABLE, build_markup, final_text, options_of
from flowpost.services.watermark import Watermarker, WatermarkSkipped, wm_cache_key, wm_configured

log = logging.getLogger(__name__)


class EmptyPostError(Exception):
    pass


@dataclass
class SendOptions:
    thread_id: int | None = None
    silent: bool = False
    protect: bool = False
    link_preview: bool = True


@dataclass
class OutMedia:
    type: str
    media: str | BufferedInputFile
    source: dict
    cache_key: str | None = None


@dataclass
class SentPart:
    ids: list[int] = field(default_factory=list)
    media_msgs: list[int] = field(default_factory=list)
    caption_msg: int | None = None
    text_msg: int | None = None
    markup_msg: int | None = None
    new_file_ids: list[str | None] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ids": self.ids,
            "media_msgs": self.media_msgs,
            "caption_msg": self.caption_msg,
            "text_msg": self.text_msg,
            "markup_msg": self.markup_msg,
        }


@dataclass
class PublishResult:
    parts: list[SentPart] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def all_ids(self) -> list[int]:
        return [i for p in self.parts for i in p.ids]


def _file_id_of(message: Message, media_type: str) -> str | None:
    if media_type == "photo" and message.photo:
        return message.photo[-1].file_id
    obj = getattr(message, media_type, None)
    return getattr(obj, "file_id", None)


def _input_media(item: OutMedia, caption: str | None):
    if item.type == "photo":
        return InputMediaPhoto(media=item.media, caption=caption)
    if item.type == "video":
        return InputMediaVideo(media=item.media, caption=caption, supports_streaming=True)
    if item.type == "document":
        return InputMediaDocument(media=item.media, caption=caption)
    if item.type == "audio":
        return InputMediaAudio(media=item.media, caption=caption)
    raise ValueError(f"{item.type} can't be part of a media group")


async def _send_single(bot: Bot, chat_id: int, item: OutMedia, **kw) -> Message:
    if item.type == "photo":
        return await bot.send_photo(chat_id, item.media, **kw)
    if item.type == "video":
        return await bot.send_video(chat_id, item.media, supports_streaming=True, **kw)
    if item.type == "animation":
        return await bot.send_animation(chat_id, item.media, **kw)
    if item.type == "document":
        return await bot.send_document(chat_id, item.media, **kw)
    if item.type == "audio":
        return await bot.send_audio(chat_id, item.media, **kw)
    raise ValueError(f"unsupported media type {item.type}")


async def send_poll_part(bot: Bot, chat_id: int, poll: dict, buttons: list[list[dict]] | None, opts: SendOptions) -> SentPart:
    markup = build_markup(buttons)
    m = await bot.send_poll(
        chat_id,
        question=poll["question"],
        options=poll["options"],
        is_anonymous=poll.get("is_anonymous", True),
        type=poll.get("type", "regular"),
        allows_multiple_answers=poll.get("allows_multiple_answers", False),
        correct_option_id=poll.get("correct_option_id"),
        explanation=poll.get("explanation"),
        open_period=poll.get("open_period"),
        reply_markup=markup,
        disable_notification=opts.silent,
        protect_content=opts.protect,
        message_thread_id=opts.thread_id,
    )
    sent = SentPart()
    sent.ids = [m.message_id]
    sent.markup_msg = m.message_id if markup else None
    return sent


async def send_part(
    bot: Bot,
    chat_id: int,
    text: str,
    media: list[OutMedia],
    buttons: list[list[dict]] | None,
    opts: SendOptions,
) -> SentPart:
    markup = build_markup(buttons)
    common = {
        "disable_notification": opts.silent,
        "protect_content": opts.protect,
        "message_thread_id": opts.thread_id,
    }
    preview = LinkPreviewOptions(is_disabled=not opts.link_preview)
    sent = SentPart()

    if not media:
        if not text.strip():
            raise EmptyPostError
        m = await bot.send_message(chat_id, text, reply_markup=markup, link_preview_options=preview, **common)
        sent.ids = [m.message_id]
        sent.text_msg = m.message_id
        sent.markup_msg = m.message_id if markup else None
        return sent

    fits = visible_len(text) <= CAPTION_LIMIT

    if len(media) == 1:
        item = media[0]
        caption = text if (fits and text) else None
        m = await _send_single(bot, chat_id, item, caption=caption, reply_markup=markup if fits else None, **common)
        sent.ids.append(m.message_id)
        sent.media_msgs = [m.message_id]
        sent.new_file_ids = [_file_id_of(m, item.type)]
        sent.caption_msg = m.message_id if caption else None
        sent.markup_msg = m.message_id if (markup and fits) else None
        if text and not fits:
            tm = await bot.send_message(chat_id, text, reply_markup=markup, link_preview_options=preview, **common)
            sent.ids.append(tm.message_id)
            sent.text_msg = tm.message_id
            sent.markup_msg = tm.message_id if markup else None
        return sent

    # Media group: Telegram doesn't allow inline buttons on albums, so buttons (and an
    # over-long text) travel in a separate message right after the album.
    move_text = bool(markup) or not fits
    group = [_input_media(item, text if (i == 0 and text and not move_text) else None) for i, item in enumerate(media)]
    msgs = await bot.send_media_group(chat_id, group, **common)
    sent.ids = [m.message_id for m in msgs]
    sent.media_msgs = list(sent.ids)
    sent.new_file_ids = [_file_id_of(m, item.type) for m, item in zip(msgs, media)]
    if text and not move_text:
        sent.caption_msg = msgs[0].message_id
    if move_text and (text or markup):
        tm = await bot.send_message(chat_id, text or "🔗", reply_markup=markup, link_preview_options=preview, **common)
        sent.ids.append(tm.message_id)
        sent.text_msg = tm.message_id
        sent.markup_msg = tm.message_id if markup else None
    return sent


class Publisher:
    def __init__(self, bot: Bot, watermarker: Watermarker | None = None):
        self.bot = bot
        self.watermarker = watermarker

    async def resolve_media(self, media_items: list[dict], channel: Channel | None, opts: dict) -> tuple[list[OutMedia], list[str]]:
        out: list[OutMedia] = []
        warnings: list[str] = []
        use_wm = bool(
            opts.get("watermark") and channel is not None and self.watermarker and wm_configured(channel.watermark)
        )
        for item in media_items:
            if use_wm and item["type"] in WATERMARKABLE:
                key = wm_cache_key(channel.id, channel.watermark)
                cached = (item.get("wm") or {}).get(key)
                if cached:
                    out.append(OutMedia(item["type"], cached, item, key))
                    continue
                try:
                    data, filename = await self.watermarker.apply(self.bot, item, channel.watermark)
                    out.append(OutMedia(item["type"], BufferedInputFile(data, filename), item, key))
                    continue
                except WatermarkSkipped as e:
                    if e.key not in warnings:
                        warnings.append(e.key)
            out.append(OutMedia(item["type"], item["file_id"], item))
        return out, warnings

    @staticmethod
    def remember_uploads(media: list[OutMedia], sent: SentPart) -> bool:
        changed = False
        for om, file_id in zip(media, sent.new_file_ids):
            if om.cache_key and isinstance(om.media, BufferedInputFile) and file_id:
                om.source.setdefault("wm", {})[om.cache_key] = file_id
                changed = True
        return changed

    async def publish_post(
        self,
        post: Post,
        channel: Channel | None,
        lang: str,
        *,
        chat_id: int | None = None,
        preview: bool = False,
        part_indexes: list[int] | None = None,
    ) -> PublishResult:
        """Send all (or selected) parts of `post`. With `preview=True` sends to `chat_id` without channel options."""
        opts = options_of(post)
        target = chat_id if chat_id is not None else channel.chat_id  # type: ignore[union-attr]
        send_opts = SendOptions(
            thread_id=None if preview or channel is None or channel.kind != "group" else (channel.topic_id or None),
            silent=False if preview else bool(opts["silent"]),
            protect=False if preview else bool(opts["protect"]),
            link_preview=bool(opts["link_preview"]),
        )
        indexes = part_indexes if part_indexes is not None else list(range(len(post.parts)))
        result = PublishResult()
        last_index = len(post.parts) - 1
        for idx in indexes:
            part = post.parts[idx]
            if part.poll:
                sent = await send_poll_part(self.bot, target, part.poll, part.buttons, send_opts)
                result.parts.append(sent)
                continue
            text = final_text(part.text_html, opts, channel, is_last=idx == last_index, lang=lang)
            media, warnings = await self.resolve_media(part.media, channel, opts)
            sent = await send_part(self.bot, target, text, media, part.buttons, send_opts)
            if self.remember_uploads(media, sent):
                flag_modified(part, "media")
            result.parts.append(sent)
            result.warnings.extend(w for w in warnings if w not in result.warnings)
        return result
