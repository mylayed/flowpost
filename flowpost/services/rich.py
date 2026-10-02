"""«Карусель»: an album sent as one rich message (Bot API 10.1+) — a `<tg-slideshow>` the reader flips through with
arrows on desktop and swipes on phones, with the post's text under it and, unlike an album, inline buttons too."""
from __future__ import annotations

import re

from aiogram.types import InputMediaPhoto, InputMediaVideo, InputRichMessage, InputRichMessageMedia, Message

CAROUSEL_TYPES = {"photo", "video"}
CAROUSEL_MIN = 2

_TAG = re.compile(r"(<[^>]+>)")
_TAG_NAME = re.compile(r"</?\s*([a-zA-Z][\w-]*)")
_BLOCKS = {"blockquote", "pre"}
_PARAGRAPH_BREAK = re.compile(r"\n{2,}")


def carousel_ready(media: list[dict]) -> bool:
    """Two or more photos/videos can go out as a carousel."""
    return len(media) >= CAROUSEL_MIN and all(item.get("type") in CAROUSEL_TYPES for item in media)


def _name(tag: str) -> str:
    m = _TAG_NAME.match(tag)
    return m.group(1).lower() if m else ""


def _inline(tag: str) -> str:
    """Telegram's `<span class="tg-spoiler">` is spelled `<tg-spoiler>` in rich HTML."""
    if _name(tag) == "span":
        return "</tg-spoiler>" if tag.startswith("</") else "<tg-spoiler>"
    return tag


def text_blocks(text_html: str) -> str:
    """Post HTML as rich HTML blocks. Rich HTML folds line breaks like a web page does, so blank lines start a new
    paragraph and single ones become `<br>`; quotes and code blocks stay blocks of their own."""
    out: list[str] = []
    para: list[str] = []
    depth = 0  # inline tags open in the current paragraph
    block: list[str] | None = None  # a blockquote/pre being copied
    block_name = ""

    def close_para() -> None:
        body = "".join(para).strip()
        if body.replace("<br>", "").strip():
            while body.startswith("<br>"):
                body = body[4:].lstrip()
            while body.endswith("<br>"):
                body = body[:-4].rstrip()
            out.append(f"<p>{body}</p>")
        para.clear()

    for token in _TAG.split(text_html or ""):
        if not token:
            continue
        if block is not None:
            if token.startswith("<"):
                block.append(_inline(token))
                if _name(token) == block_name and token.startswith("</"):
                    content = "".join(block)
                    out.append(content.replace("\n", "<br>") if block_name == "blockquote" else content)
                    block = None
            else:
                block.append(token)
            continue
        if token.startswith("<"):
            name = _name(token)
            if name in _BLOCKS and depth == 0 and not token.startswith("</"):
                close_para()
                block, block_name = [token], name
                continue
            if token.endswith("/>") or name == "br":
                para.append(token)
                continue
            depth += -1 if token.startswith("</") else 1
            depth = max(depth, 0)
            para.append(_inline(token))
            continue
        chunks = _PARAGRAPH_BREAK.split(token) if depth == 0 else [token]
        for i, chunk in enumerate(chunks):
            if i:
                close_para()
            para.append(chunk.replace("\n", "<br>"))
    if block is not None:
        out.append("".join(block))
    close_para()
    return "".join(out)


def build(text_html: str, media: list[tuple[str, object]]) -> InputRichMessage:
    """A carousel of `media` ((type, file id or upload) pairs) with the post text under it."""
    slides: list[str] = []
    attached: list[InputRichMessageMedia] = []
    for i, (kind, file) in enumerate(media):
        ref = f"m{i}"
        if kind == "photo":
            slides.append(f'<img src="tg://photo?id={ref}"/>')
            attached.append(InputRichMessageMedia(id=ref, media=InputMediaPhoto(media=file)))
        else:
            slides.append(f'<video src="tg://video?id={ref}"/>')
            attached.append(InputRichMessageMedia(id=ref, media=InputMediaVideo(media=file, supports_streaming=True)))
    html = "<tg-slideshow>" + "".join(slides) + "</tg-slideshow>" + text_blocks(text_html)
    return InputRichMessage(html=html, media=attached)


def sent_file_ids(message: Message) -> list[str | None]:
    """File ids of the carousel's slides as Telegram stored them, in order (to reuse watermarked uploads)."""
    rich = getattr(message, "rich_message", None)
    for block in (rich.blocks if rich else []) or []:
        if getattr(block, "type", None) != "slideshow":
            continue
        ids: list[str | None] = []
        for slide in block.blocks or []:
            photo = getattr(slide, "photo", None)
            video = getattr(slide, "video", None)
            ids.append(photo[-1].file_id if photo else getattr(video, "file_id", None))
        return ids
    return []
