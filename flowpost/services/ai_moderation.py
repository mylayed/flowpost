"""PRO AI moderation of discussion comments: comments that passed the word/link filters wait here and are checked
by AI in batches, so one «ai_mod» check of the channel covers up to `ai_mod_batch` comments."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Pending:
    chat_id: int
    message_id: int
    user_tg_id: int
    text: str
    publication_id: int | None  # the post it was counted as a comment on, if any
    author: str = ""  # the author's display name
    media_file_id: str | None = None  # a small image of the attached photo/GIF/video/sticker, checked for sexual content
    urgent: bool = False  # has a picture or an author not yet checked: a likely porn bot, so checked without waiting


@dataclass
class _Batch:
    since: float
    items: list[Pending] = field(default_factory=list)
    urgent: bool = False


def media_file_id(message) -> str | None:
    """A small still image of what's attached to `message` (a photo, or a GIF/video/sticker frame), if anything."""
    if message.photo:
        fitting = [p for p in message.photo if max(p.width, p.height) <= 800]
        return (fitting[-1] if fitting else message.photo[0]).file_id
    sticker = message.sticker
    if sticker is not None:
        if not sticker.is_animated and not sticker.is_video:
            return sticker.file_id  # a static sticker is itself a .webp image
        return sticker.thumbnail.file_id if sticker.thumbnail else None
    for media in (message.animation, message.video, message.video_note, message.document):
        if media is not None and media.thumbnail is not None:
            return media.thumbnail.file_id
    return None


def buttons_text(message) -> str:
    """The inline buttons a comment carries (a forwarded ad keeps them), as «label url» lines: spam hides its links there."""
    markup = message.reply_markup
    if markup is None or not getattr(markup, "inline_keyboard", None):
        return ""
    return "\n".join(
        " ".join(part for part in (b.text, b.url or "") if part)
        for row in markup.inline_keyboard for b in row
    )


def image_type(data: bytes) -> str | None:
    """The media type of an image Claude accepts, by its magic bytes; None for anything else."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


class Queue:
    """Comments waiting for an AI check, per channel. Kept in memory: a restart only loses a minute of checks."""

    MAX_PER_CHANNEL = 500  # a runaway flood can't grow memory without bound; the extra comments go unchecked

    def __init__(self, batch: int, wait_seconds: float):
        self.batch = batch
        self.wait_seconds = wait_seconds
        self._pending: dict[int, _Batch] = {}

    def add(self, channel_id: int, item: Pending, *, now: float | None = None) -> bool:
        """Queue a comment; True once the channel has a full or urgent batch waiting, so it can be checked right away."""
        now = time.monotonic() if now is None else now
        pending = self._pending.setdefault(channel_id, _Batch(since=now))
        if len(pending.items) < self.MAX_PER_CHANNEL:
            pending.items.append(item)
            pending.urgent = pending.urgent or item.urgent
        return pending.urgent or len(pending.items) >= self.batch

    def due(self, *, now: float | None = None, flush: bool = False) -> list[tuple[int, list[Pending]]]:
        """Take the batches ready to be checked: full or urgent ones, ones whose oldest comment waited long enough,
        or all."""
        now = time.monotonic() if now is None else now
        ready: list[tuple[int, list[Pending]]] = []
        for channel_id in list(self._pending):
            pending = self._pending[channel_id]
            if flush or pending.urgent or now - pending.since >= self.wait_seconds:
                del self._pending[channel_id]
                items = pending.items
            elif len(pending.items) >= self.batch:
                items, pending.items = pending.items[:self.batch], pending.items[self.batch:]
                pending.since = now
            else:
                continue
            ready += [(channel_id, items[i:i + self.batch]) for i in range(0, len(items), self.batch)]
        return ready
