"""Watermarks: Pillow for photos, ffmpeg for videos and GIFs."""
from __future__ import annotations

import asyncio
import collections
import hashlib
import io
import json
import logging
import os
import shutil
import tempfile

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from PIL import Image, ImageDraw, ImageFont, ImageOps

log = logging.getLogger(__name__)

MAX_DOWNLOAD = 20 * 1024 * 1024  # cloud Bot API getFile limit
MAX_UPLOAD = 50 * 1024 * 1024
MAX_KEPT_RENDERS = 2  # finished video renders held in memory, up to MAX_UPLOAD each
POSITIONS = ["tl", "tc", "tr", "ml", "mc", "mr", "bl", "bc", "br"]
DEFAULT_WM: dict = {"type": "text", "text": "", "image_file_id": None, "position": "br", "opacity": 60, "scale": 25}

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


class WatermarkSkipped(Exception):
    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


def wm_settings(raw: dict | None) -> dict:
    return {**DEFAULT_WM, **(raw or {})}


def wm_configured(raw: dict | None) -> bool:
    s = wm_settings(raw)
    if s["type"] == "image":
        return bool(s["image_file_id"])
    return bool((s["text"] or "").strip())


def item_wm(item: dict, post_enabled: bool, channel_wm: dict | None) -> dict | None:
    """Effective watermark for one media item, or None. An item may override the post: `wm_mode` "on"/"off"
    and `wm_custom` — its own text or logo on top of the channel's position/opacity/size."""
    mode = item.get("wm_mode")
    if not (mode == "on" if mode in ("on", "off") else post_enabled):
        return None
    raw = {**(channel_wm or {}), **(item.get("wm_custom") or {})}
    return raw if wm_configured(raw) else None


def wm_cache_key(channel_id: int, raw: dict | None) -> str:
    digest = hashlib.sha1(json.dumps(wm_settings(raw), sort_keys=True).encode()).hexdigest()[:10]
    return f"{channel_id}:{digest}"


def find_font(explicit: str | None = None) -> str | None:
    for path in [explicit, *FONT_CANDIDATES]:
        if path and os.path.exists(path):
            return path
    return None


def _font(path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def build_overlay(width: int, height: int, s: dict, logo: bytes | None, font_path: str | None) -> Image.Image:
    target_w = max(24, int(width * max(5, min(90, int(s["scale"]))) / 100))
    alpha = max(5, min(100, int(s["opacity"]))) / 100

    if s["type"] == "image" and logo:
        img = Image.open(io.BytesIO(logo)).convert("RGBA")
        ratio = target_w / img.width
        img = img.resize((target_w, max(1, int(img.height * ratio))), Image.LANCZOS)
        a = img.getchannel("A").point(lambda v: int(v * alpha))
        img.putalpha(a)
        return img

    text = (s["text"] or "").strip() or " "
    size = max(10, target_w // max(1, len(text)) * 2)
    font = _font(font_path, size)
    left, top, right, bottom = font.getbbox(text)
    if right - left > 0:
        size = max(10, int(size * target_w / (right - left)))
        size = min(size, max(10, height // 4))
        font = _font(font_path, size)
        left, top, right, bottom = font.getbbox(text)
    shadow = max(1, size // 18)
    canvas = Image.new("RGBA", (right - left + shadow * 2 + 2, bottom - top + shadow * 2 + 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((-left + shadow * 2, -top + shadow * 2), text, font=font, fill=(0, 0, 0, int(150 * alpha)))
    draw.text((-left, -top), text, font=font, fill=(255, 255, 255, int(255 * alpha)))
    return canvas


def position_xy(base: tuple[int, int], overlay: tuple[int, int], position: str) -> tuple[int, int]:
    bw, bh = base
    ow, oh = overlay
    margin = max(4, int(min(bw, bh) * 0.03))
    position = position if position in POSITIONS else "br"
    row, col = position[0], position[1]
    x = {"l": margin, "c": (bw - ow) // 2, "r": bw - ow - margin}[col]
    y = {"t": margin, "m": (bh - oh) // 2, "b": bh - oh - margin}[row]
    return max(0, x), max(0, y)


def render_photo(src: bytes, s: dict, logo: bytes | None, font_path: str | None) -> bytes:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(src))).convert("RGBA")
    overlay = build_overlay(img.width, img.height, s, logo, font_path)
    img.alpha_composite(overlay, position_xy(img.size, overlay.size, s["position"]))
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=92)
    return out.getvalue()


class Watermarker:
    def __init__(self, ffmpeg_bin: str = "ffmpeg", font_path: str | None = None, concurrency: int = 2):
        self.ffmpeg_bin = ffmpeg_bin
        self.font_path = find_font(font_path)
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self._logo_cache: dict[str, bytes] = {}
        # A video takes long enough to render that the editor draws its preview in the background. The result is
        # kept for a moment so the preview that follows picks it up instead of encoding the video a second time,
        # and a render already running is joined rather than started again.
        self._rendered: collections.OrderedDict[tuple[str, str], tuple[bytes, str]] = collections.OrderedDict()
        self._inflight: dict[tuple[str, str], asyncio.Future] = {}

    @property
    def ffmpeg_available(self) -> bool:
        return shutil.which(self.ffmpeg_bin) is not None

    async def _download(self, bot: Bot, file_id: str) -> bytes:
        try:
            buf = await bot.download(file_id)
        except TelegramBadRequest as e:
            log.warning("watermark download failed: %s", e)
            raise WatermarkSkipped("warn.wm_too_big") from e
        assert buf is not None
        return buf.getvalue()

    async def _logo(self, bot: Bot, s: dict) -> bytes | None:
        file_id = s.get("image_file_id")
        if not file_id:
            return None
        if file_id not in self._logo_cache:
            self._logo_cache[file_id] = await self._download(bot, file_id)
        return self._logo_cache[file_id]

    async def apply(self, bot: Bot, item: dict, raw_settings: dict | None) -> tuple[bytes, str]:
        key = (item["file_id"], wm_cache_key(0, raw_settings))
        if key in self._rendered:
            self._rendered.move_to_end(key)
            return self._rendered[key]
        task = self._inflight.get(key)
        if task is None:
            task = self._inflight[key] = asyncio.ensure_future(self._render(bot, item, wm_settings(raw_settings)))
            task.add_done_callback(lambda done, key=key, video=item["type"] != "photo": self._finished(key, done, video))
        return await asyncio.shield(task)

    def _finished(self, key: tuple[str, str], task: asyncio.Future, video: bool) -> None:
        self._inflight.pop(key, None)
        if task.cancelled() or task.exception() is not None:  # calling exception() also marks it as retrieved
            return
        if video:  # photos are quick to redo and would only crowd the memory
            self._rendered[key] = task.result()
            while len(self._rendered) > MAX_KEPT_RENDERS:
                self._rendered.popitem(last=False)

    async def _render(self, bot: Bot, item: dict, s: dict) -> tuple[bytes, str]:
        if item.get("size") and item["size"] > MAX_DOWNLOAD:
            raise WatermarkSkipped("warn.wm_too_big")
        is_video = item["type"] in ("video", "animation")
        if is_video and not self.ffmpeg_available:
            raise WatermarkSkipped("warn.wm_no_ffmpeg")
        async with self._sem:
            src = await self._download(bot, item["file_id"])
            logo = await self._logo(bot, s) if s["type"] == "image" else None
            if not is_video:
                return await asyncio.to_thread(render_photo, src, s, logo, self.font_path), "photo.jpg"
            return await self._render_video(src, item, s, logo), "video.mp4"

    async def _render_video(self, src: bytes, item: dict, s: dict, logo: bytes | None) -> bytes:
        width, height = int(item.get("w") or 1280), int(item.get("h") or 720)
        overlay = await asyncio.to_thread(build_overlay, width, height, s, logo, self.font_path)
        x, y = position_xy((width, height), overlay.size, s["position"])
        with tempfile.TemporaryDirectory() as tmp:
            inp, png, out = (os.path.join(tmp, n) for n in ("in.mp4", "wm.png", "out.mp4"))
            with open(inp, "wb") as f:
                f.write(src)
            overlay.save(png)
            cmd = [
                self.ffmpeg_bin, "-y", "-loglevel", "error", "-i", inp, "-i", png,
                "-filter_complex", f"[0:v][1:v]overlay={x}:{y},scale=trunc(iw/2)*2:trunc(ih/2)*2[v]",
                "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24",
                "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                _, err = await asyncio.wait_for(proc.communicate(), timeout=300)
            except asyncio.TimeoutError as e:
                proc.kill()
                raise WatermarkSkipped("warn.wm_failed") from e
            if proc.returncode != 0 or not os.path.exists(out):
                log.warning("ffmpeg failed: %s", err.decode(errors="ignore")[-500:])
                raise WatermarkSkipped("warn.wm_failed")
            if os.path.getsize(out) > MAX_UPLOAD:
                raise WatermarkSkipped("warn.wm_too_big")
            with open(out, "rb") as f:
                return f.read()
