"""Editor → «Альбом»: one album item at a time — preview, order, delete, replace, per-item and album-wide watermark."""
from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.channel_settings import MAX_WM_TEXT
from flowpost.bot.handlers.create_post import extract_content
from flowpost.bot.handlers.editor.view import (
    NO_PREVIEW,
    load_editor_post,
    post_from_callback,
    render_editor,
    safe_delete,
    show_panel,
)
from flowpost.bot.keyboards.common import btn, chunked, markup, on
from flowpost.bot.states import Editor
from flowpost.db.models import Channel, Post, User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services.billing import entitlements
from flowpost.services.posts import MAX_MEDIA, WATERMARKABLE, group_error, media_icon, options_of
from flowpost.services.publisher import Publisher
from flowpost.services.watermark import item_wm, wm_configured

log = logging.getLogger(__name__)
router = Router(name="editor_album")
MEDIA = F.photo | F.video | F.animation | F.document | F.audio
# Item keys that belong to the album slot rather than to the file, so they survive replacing the file.
SLOT_KEYS = ("wm_mode", "wm_custom")


async def _channel(session: AsyncSession, user: User, post: Post) -> Channel | None:
    channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
    return channels[0] if channels else None


def _index(value: str, total: int) -> int:
    i = int(value) if value.isdigit() else 0
    return max(0, min(i, total - 1))


def _wm_status(item: dict, post: Post, channel: Channel | None) -> str:
    if item["type"] not in WATERMARKABLE:
        return t("alb.wm_unsupported")
    applied = item_wm(item, options_of(post)["watermark"], channel.watermark if channel else None) is not None
    state = t("alb.wm_on") if applied else t("alb.wm_off")
    if item.get("wm_mode") not in ("on", "off"):
        state += " " + t("alb.wm_as_album")
    if applied and item.get("wm_custom"):
        custom = item["wm_custom"]
        state += " · " + (t("alb.wm_own_image") if custom.get("type") == "image"
                          else t("alb.wm_own_text", text=html.escape(custom.get("text") or "")))
    return state


def album_screen(post: Post, idx: int, i: int, channel: Channel | None, note: str | None = None):
    part = post.parts[idx]
    p = post.id
    items = part.media
    item = items[i]
    lines = [
        t("alb.title", n=i + 1, total=len(items), icon=media_icon(item)),
        t("alb.wm_status", status=_wm_status(item, post, channel)),
        "",
        t("alb.help"),
    ]
    if note:
        lines += ["", note]
    numbers = [btn(f"• {j + 1} •" if j == i else str(j + 1), Ed(a="alb", p=p, v=str(j))) for j in range(len(items))]
    rows = chunked(numbers, 5)
    if item["type"] in WATERMARKABLE:
        rows.append([btn(t("alb.wm_item"), Ed(a="alb_wm", p=p, v=str(i)))])
    rows.append([btn(t("alb.move"), Ed(a="alb_mv", p=p, v=str(i))), btn(t("alb.delete"), Ed(a="alb_del", p=p, v=str(i)))])
    rows.append([btn(t("alb.wm_all"), Ed(a="alb_wma", p=p, v=str(i)))])
    if len(items) < MAX_MEDIA:
        rows.append([btn(t("alb.add"), Ed(a="m_add", p=p, v="alb"))])
    rows.append([btn(t("media_menu.clear"), Ed(a="m_clear", p=p, v="alb"))])
    rows.append([btn(t("btn.back"), Ed(a="home", p=p))])
    return "\n".join(lines), markup(rows)


async def show_album(
    bot: Bot,
    chat_id: int,
    session: AsyncSession,
    state: FSMContext,
    user: User,
    post: Post,
    publisher: Publisher,
    i: int | None = None,
    *,
    note: str | None = None,
) -> None:
    """Preview of the chosen album item with its control panel underneath; falls back to the editor for ≤1 media."""
    data = await state.get_data()
    idx = int(data.get("part", 0))
    idx = max(0, min(idx, len(post.parts) - 1))
    items = post.parts[idx].media
    if len(items) < 2:
        await render_editor(bot, chat_id, session, state, user, post, publisher, note=note)
        return
    i = _index(str(data.get("alb_i", 0) if i is None else i), len(items))
    channel = await _channel(session, user, post)
    await safe_delete(bot, chat_id, list(data.get("preview_ids") or []) + [data.get("panel_id")])
    preview_ids: list[int] = []
    notes = [note] if note else []
    try:
        channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
        message_id, warnings = await publisher.preview_item(
            chat_id, items[i], channel, options_of(post), session,
            wm_allowed=await entitlements.extras_allowed(session, channels, utcnow()),
        )
        preview_ids.append(message_id)
        notes += ["⚠️ " + t(key) for key in warnings]
    except TelegramBadRequest as e:
        log.info("album preview failed: %s", e)
        notes.append(t("warn.preview_failed", error=html.escape(e.message)))
    text, kb = album_screen(post, idx, i, channel, "\n".join(notes) or None)
    panel = await bot.send_message(chat_id, text, reply_markup=kb, link_preview_options=NO_PREVIEW)
    await state.set_state(Editor.album)
    await state.update_data(post_id=post.id, part=idx, alb_i=i, preview_ids=preview_ids, panel_id=panel.message_id)


async def _set_media(session: AsyncSession, post: Post, idx: int, items: list[dict]) -> None:
    post.parts[idx].media = items
    await session.flush()


# ---- callbacks ----------------------------------------------------------------------------------

@router.callback_query(Ed.filter(F.a == "alb"))
async def alb_open(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    i = int(callback_data.v) if callback_data.v.isdigit() else None
    await show_album(bot, cb.from_user.id, session, state, user, post, publisher, i)


@router.callback_query(Ed.filter(F.a == "alb_mv"))
async def alb_move_menu(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    items = post.parts[idx].media
    i = _index(callback_data.v, len(items))
    await cb.answer()
    await state.set_state(Editor.album)
    numbers = [
        btn(("✅ " if j == i else "") + f"{j + 1} {media_icon(m)}", Ed(a="alb_sw", p=post.id, v=f"{i}_{j}"))
        for j, m in enumerate(items)
    ]
    kb = markup(chunked(numbers, 5) + [[btn(t("btn.back"), Ed(a="alb", p=post.id, v=str(i)))]])
    await show_panel(bot, cb.from_user.id, state, t("alb.move_prompt", n=i + 1), kb)


@router.callback_query(Ed.filter(F.a == "alb_sw"))
async def alb_swap(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    items = list(post.parts[idx].media)
    src, _, dst = callback_data.v.partition("_")
    i, j = _index(src, len(items)), _index(dst, len(items))
    await cb.answer()
    if i != j:
        items[i], items[j] = items[j], items[i]
        await _set_media(session, post, idx, items)
    await show_album(bot, cb.from_user.id, session, state, user, post, publisher, j,
                     note=t("alb.moved", src=i + 1, dst=j + 1) if i != j else None)


@router.callback_query(Ed.filter(F.a == "alb_del"))
async def alb_delete(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    items = list(post.parts[idx].media)
    i = _index(callback_data.v, len(items))
    items.pop(i)
    await _set_media(session, post, idx, items)
    await cb.answer(t("alb.deleted"))
    await show_album(bot, cb.from_user.id, session, state, user, post, publisher, min(i, len(items) - 1),
                     note=t("alb.deleted"))


@router.callback_query(Ed.filter(F.a == "alb_wm"))
async def alb_item_wm_menu(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    items = post.parts[idx].media
    i = _index(callback_data.v, len(items))
    item = items[i]
    channel = await _channel(session, user, post)
    await cb.answer()
    await state.set_state(Editor.album)
    mode = item.get("wm_mode")
    p = post.id
    rows = [
        [btn(on(mode == "on") + t("alb.wm_mode_on"), Ed(a="alb_wms", p=p, v=f"{i}_on"))],
        [btn(on(mode == "off") + t("alb.wm_mode_off"), Ed(a="alb_wms", p=p, v=f"{i}_off"))],
        [btn(on(mode not in ("on", "off")) + t("alb.wm_mode_album"), Ed(a="alb_wms", p=p, v=f"{i}_album"))],
        [btn(t("alb.wm_custom"), Ed(a="alb_wmc", p=p, v=str(i)))],
    ]
    if item.get("wm_custom"):
        rows.append([btn(t("alb.wm_custom_reset"), Ed(a="alb_wms", p=p, v=f"{i}_nocustom"))])
    rows.append([btn(t("btn.back"), Ed(a="alb", p=p, v=str(i)))])
    text = "\n".join([
        t("alb.wm_item_title", n=i + 1, total=len(items)),
        t("alb.wm_status", status=_wm_status(item, post, channel)),
        "",
        t("alb.wm_item_help"),
    ])
    await show_panel(bot, cb.from_user.id, state, text, markup(rows))


@router.callback_query(Ed.filter(F.a == "alb_wms"))
async def alb_item_wm_set(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    items = [dict(m) for m in post.parts[idx].media]
    raw_i, _, action = callback_data.v.partition("_")
    i = _index(raw_i, len(items))
    item = items[i]
    channel = await _channel(session, user, post)
    if action == "on":
        if not wm_configured({**((channel.watermark if channel else None) or {}), **(item.get("wm_custom") or {})}):
            await cb.answer(t("alb.wm_need_setup"), show_alert=True)
            return
        item["wm_mode"] = "on"
    elif action == "off":
        item["wm_mode"] = "off"
    elif action == "album":
        item.pop("wm_mode", None)
    elif action == "nocustom":
        item.pop("wm_custom", None)
    await _set_media(session, post, idx, items)
    await cb.answer(t("alb.saved"))
    await show_album(bot, cb.from_user.id, session, state, user, post, publisher, i, note=t("alb.saved"))


@router.callback_query(Ed.filter(F.a == "alb_wma"))
async def alb_all_wm_menu(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    items = post.parts[idx].media
    i = _index(callback_data.v or str((await state.get_data()).get("alb_i", 0)), len(items))
    await cb.answer()
    await state.set_state(Editor.album)
    await state.update_data(alb_i=i)
    p = post.id
    enabled = options_of(post)["watermark"]
    overrides = sum(1 for m in items if m.get("wm_mode") in ("on", "off") or m.get("wm_custom"))
    lines = [t("alb.wm_all_title"), t("alb.wm_status", status=t("alb.wm_on") if enabled else t("alb.wm_off"))]
    if overrides:
        lines.append(t("alb.wm_overrides", n=overrides))
    lines += ["", t("alb.wm_all_help")]
    rows = [
        [btn(on(enabled) + t("alb.wm_all_on"), Ed(a="alb_wmall", p=p, v="on")),
         btn(on(not enabled) + t("alb.wm_all_off"), Ed(a="alb_wmall", p=p, v="off"))],
        [btn(t("alb.wm_custom_all"), Ed(a="alb_wmc", p=p, v="all"))],
        [btn(t("alb.wm_channel"), Ed(a="wm", p=p))],
        [btn(t("btn.back"), Ed(a="alb", p=p, v=str(i)))],
    ]
    await show_panel(bot, cb.from_user.id, state, "\n".join(lines), markup(rows))


@router.callback_query(Ed.filter(F.a == "alb_wmall"))
async def alb_all_wm_set(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    enable = callback_data.v == "on"
    items = [dict(m) for m in post.parts[idx].media]
    channel = await _channel(session, user, post)
    channel_wm = (channel.watermark if channel else None) or {}
    if enable and not all(wm_configured({**channel_wm, **(m.get("wm_custom") or {})})
                          for m in items if m["type"] in WATERMARKABLE):
        await cb.answer(t("alb.wm_need_setup"), show_alert=True)
        return
    # «На всі» is a reset: per-item on/off choices give way to the album-wide one; own texts/logos stay.
    for m in items:
        m.pop("wm_mode", None)
    post.options = {**(post.options or {}), "watermark": enable}
    await _set_media(session, post, idx, items)
    await cb.answer(t("alb.saved"))
    await show_album(bot, cb.from_user.id, session, state, user, post, publisher,
                     note=t("alb.wm_all_enabled") if enable else t("alb.wm_all_disabled"))


@router.callback_query(Ed.filter(F.a == "alb_wmc"))
async def alb_custom_wm_prompt(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    target = "all" if callback_data.v == "all" else str(_index(callback_data.v, len(post.parts[idx].media)))
    await state.set_state(Editor.album_wm)
    await state.update_data(alb_wm_target=target)
    back = Ed(a="alb_wma", p=post.id) if target == "all" else Ed(a="alb_wm", p=post.id, v=target)
    await show_panel(bot, cb.from_user.id, state, t("alb.wm_custom_prompt", max=MAX_WM_TEXT),
                     markup([[btn(t("btn.back"), back)]]))


# ---- messages -----------------------------------------------------------------------------------

@router.message(Editor.album_wm, F.text | F.photo | F.document)
async def alb_custom_wm_received(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher
) -> None:
    post, idx = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    if message.text:
        text = message.text.strip()
        if not text or text.startswith("/") or len(text) > MAX_WM_TEXT:
            await message.answer(t("alb.wm_custom_prompt", max=MAX_WM_TEXT))
            return
        custom = {"type": "text", "text": text, "image_file_id": None}
    else:
        if message.document and not (message.document.mime_type or "").startswith("image/"):
            await message.answer(t("alb.wm_custom_prompt", max=MAX_WM_TEXT))
            return
        file_id = message.document.file_id if message.document else message.photo[-1].file_id
        custom = {"type": "image", "image_file_id": file_id}
    data = await state.get_data()
    target = data.get("alb_wm_target", "all")
    items = [dict(m) for m in post.parts[idx].media]
    chosen = range(len(items)) if target == "all" else [_index(str(target), len(items))]
    for j in chosen:
        if items[j]["type"] in WATERMARKABLE:
            items[j]["wm_custom"] = custom
            if target != "all":
                items[j]["wm_mode"] = "on"
    if target == "all":
        post.options = {**(post.options or {}), "watermark": True}
    await _set_media(session, post, idx, items)
    i = None if target == "all" else int(target)
    await show_album(bot, message.chat.id, session, state, user, post, publisher, i, note=t("alb.saved"))


@router.message(Editor.album_wm)
async def alb_custom_wm_wrong(message: Message) -> None:
    await message.answer(t("alb.wm_custom_prompt", max=MAX_WM_TEXT))


@router.message(Editor.album, MEDIA)
async def alb_replace_item(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    state: FSMContext,
    user: User,
    publisher: Publisher,
    album: list[Message] | None = None,
) -> None:
    post, idx = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    _, media, _ = extract_content(album or [message])
    if len(media) != 1:
        await message.answer(t("alb.one_file"))
        return
    items = [dict(m) for m in post.parts[idx].media]
    i = _index(str((await state.get_data()).get("alb_i", 0)), len(items))
    new_item = {**media[0], **{k: items[i][k] for k in SLOT_KEYS if k in items[i]}}
    candidate = items[:i] + [new_item] + items[i + 1:]
    error = group_error(candidate)
    if error:
        await message.answer(t(error))
        return
    await _set_media(session, post, idx, candidate)
    await show_album(bot, message.chat.id, session, state, user, post, publisher, i, note=t("alb.replaced"))


@router.message(Editor.album)
async def alb_wrong(message: Message) -> None:
    await message.answer(t("alb.help"))
