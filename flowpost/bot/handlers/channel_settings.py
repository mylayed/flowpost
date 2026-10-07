"""Per-channel settings shared by the editor and «Мої проєкти»: watermark, signature, AI style, topic."""
from __future__ import annotations

import html
import re
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    WebAppInfo,
)
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ca, Cs, Ed, Pj, Px
from flowpost.bot.handlers.editor.view import render_editor
from flowpost.bot.keyboards.common import btn, markup, on
from flowpost.bot.keyboards.main_menu import link_discussion_kb
from flowpost.bot.states import ChannelInput
from flowpost.config import Settings
from flowpost.db.models import Channel, Post, User
from flowpost.db.repo import channel_admins as channel_admins_repo
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.db.repo import publications as pubs_repo
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services.auto_comment import MAX_AUTO_COMMENT, auto_comment_settings
from flowpost.services.growth import handles_requests
from flowpost.services.delivery import engagement_score, publication_message_ids, reactions_total
from flowpost.services.html_sanitize import sanitize_html, snippet, visible_len
from flowpost.services.moderation import MAX_BANNED_WORDS, moderation_settings
from flowpost.services.parsing import ParseError, parse_topic
from flowpost.services.posts import (
    message_link, options_of, part_preview_text, render_signature, signature_templates,
)
from flowpost.services.publisher import Publisher
from flowpost.services.watermark import POSITIONS, wm_configured, wm_settings

STATS_PERIODS = (7, 30)
STATS_TOP_N = 10

router = Router(name="channel_settings")

POSITION_ICONS = {"tl": "↖️", "tc": "⬆️", "tr": "↗️", "ml": "⬅️", "mc": "⏺", "mr": "➡️", "bl": "↙️", "bc": "⬇️", "br": "↘️"}
MAX_WM_TEXT = 40
MAX_SIGNATURE = 512
MAX_SIGNATURE_TEMPLATES = 10
MAX_STYLE = 1500


# ---- screens ------------------------------------------------------------------------------------

def back_button(channel: Channel, post_id: int):
    return btn(t("btn.back"), Ed(a="home", p=post_id) if post_id else Pj(a="ch", c=channel.id))


def channel_card(
    channel: Channel, *, is_owner: bool = True, can_disconnect: bool = True, can_settings: bool = True,
    can_posts: bool = True, calendar_url: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    wm = wm_settings(channel.watermark)
    kind = t("proj.kind_channel") if channel.kind == "channel" else t("proj.kind_group")
    recipients = channel.notify_recipients or "owner"
    lines = [
        f"{'📢' if channel.kind == 'channel' else '👥'} <b>{html.escape(channel.title)}</b>",
        t("proj.kind", kind=kind) + (f" · @{channel.username}" if channel.username else ""),
        t("proj.status_active") if channel.is_active else t("proj.status_inactive"),
        "",
        t("proj.signature", signature=render_signature(channel)) if channel.signature_on else t("proj.signature_off"),
        t("proj.watermark_on") if wm_configured(channel.watermark) and wm.get("enabled") else t("proj.watermark_off"),
        t("proj.ai_style_set") if channel.ai_style_prompt else t("proj.ai_style_none"),
        t("proj.notify_on", recipients=t(f"proj.notify_recipients_{recipients}")) if channel.notify_published
        else t("proj.notify_off"),
        t("proj.comments_on", title=html.escape(channel.discussion_title or "")) if channel.discussion_chat_id
        else t("proj.comments_off"),
        t("proj.gap_on") if channel.gap_reminder else t("proj.gap_off"),
    ]
    if channel.is_forum:
        lines.append(t("proj.topic", topic=channel.topic_id or t("proj.topic_general")))
    c = channel.id
    rows = []
    if calendar_url:
        rows.append([InlineKeyboardButton(text=t("proj.calendar_btn"), web_app=WebAppInfo(url=calendar_url))])
    if can_posts:
        rows.append([btn(t("pro.ideas"), Px(a="ideas", c=c, v="ch"))])
    rows.append([btn(t("ed.signature"), Cs(a="sig", c=c)), btn(t("ed.watermark"), Cs(a="wm", c=c))])
    if can_settings:
        rows.append([btn(t("proj.ai_style_btn"), Cs(a="ai_style", c=c)), btn(t("proj.comments_btn"), Cs(a="cm", c=c))])
        rows.append([btn(on(handles_requests(channel)) + t("pro.join"), Px(a="join", c=c))])
    stats = btn(t("proj.stats_btn"), Cs(a="stats", c=c, v="7"))
    rows.append([stats, btn(t("gw.btn"), Px(a="gw", c=c))] if can_settings else [stats])
    if can_settings:
        rows.append([btn(t("pro.btn"), Px(a="menu", c=c))])
        rows.append(
            [btn(t("proj.notify_toggle_on") if channel.notify_published else t("proj.notify_toggle_off"), Cs(a="notify_def", c=c))]
        )
        if channel.notify_published:
            rows.append([
                btn(on(recipients == "owner") + t("proj.notify_rcpt_owner"), Cs(a="notify_rcpt", c=c, v="owner")),
                btn(on(recipients == "admin") + t("proj.notify_rcpt_admin"), Cs(a="notify_rcpt", c=c, v="admin")),
                btn(on(recipients == "both") + t("proj.notify_rcpt_both"), Cs(a="notify_rcpt", c=c, v="both")),
            ])
        rows.append([btn(t("proj.gap_toggle_on") if channel.gap_reminder else t("proj.gap_toggle_off"), Cs(a="gap_t", c=c))])
        if channel.is_forum:
            rows.append([btn(t("btn.topic_set"), Cs(a="topic", c=c))])
    if is_owner:
        rows.append([btn(t("admins.manage_btn"), Ca(a="list", c=c))])
    if is_owner or can_disconnect:
        rows.append([btn(t("proj.disconnect"), Pj(a="off", c=c))])
    rows.append([btn(t("btn.back"), Pj(a="list"))])
    return "\n".join(lines), markup(rows)


async def card_kwargs(session: AsyncSession, channel: Channel, user: User, settings: Settings) -> dict:
    is_owner = channel.owner_id == user.id
    can_disconnect = is_owner or await channel_admins_repo.has_permission(session, channel.id, user.id, "disconnect")
    can_settings = is_owner or await channel_admins_repo.has_permission(session, channel.id, user.id, "settings")
    can_posts = is_owner or await channel_admins_repo.has_permission(session, channel.id, user.id, "posts")
    calendar_url = settings.calendar_url(channel.id) if can_posts else None
    return {
        "is_owner": is_owner, "can_disconnect": can_disconnect, "can_settings": can_settings, "can_posts": can_posts,
        "calendar_url": calendar_url,
    }


def wm_menu(channel: Channel, post: Post | None, *, can_settings: bool = True) -> tuple[str, InlineKeyboardMarkup]:
    s = wm_settings(channel.watermark)
    p = post.id if post else 0
    c = channel.id
    lines = [t("wm.title", title=html.escape(channel.title))]
    if s["type"] == "image" and s["image_file_id"]:
        lines.append(t("wm.kind_image"))
    elif s["text"]:
        lines.append(t("wm.kind_text", text=html.escape(s["text"])))
    else:
        lines.append(t("wm.not_set"))
    lines.append(t("wm.params", position=POSITION_ICONS[s["position"]], opacity=s["opacity"], scale=s["scale"]))
    lines += ["", t("wm.help")]
    rows = []
    if post is not None:
        rows.append([btn(on(options_of(post)["watermark"]) + t("wm.apply_post"), Cs(a="wm_post", c=c, p=p))])
    if can_settings:
        rows += [
            [btn(t("wm.set_text"), Cs(a="wm_text", c=c, p=p)), btn(t("wm.set_image"), Cs(a="wm_img", c=c, p=p))],
            [btn(t("wm.position"), Cs(a="wm_posm", c=c, p=p))],
            [btn("➖", Cs(a="wm_op", c=c, p=p, v="-10")), btn(t("wm.opacity_short", v=s["opacity"]), Cs(a="noop", c=c, p=p)),
             btn("➕", Cs(a="wm_op", c=c, p=p, v="10"))],
            [btn("➖", Cs(a="wm_sc", c=c, p=p, v="-5")), btn(t("wm.scale_short", v=s["scale"]), Cs(a="noop", c=c, p=p)),
             btn("➕", Cs(a="wm_sc", c=c, p=p, v="5"))],
            [btn(on(bool(s.get("enabled"))) + t("wm.default_toggle"), Cs(a="wm_def", c=c, p=p))],
        ]
    rows.append([back_button(channel, p)])
    return "\n".join(lines), markup(rows)


def wm_position_menu(channel: Channel, post_id: int) -> tuple[str, InlineKeyboardMarkup]:
    current = wm_settings(channel.watermark)["position"]
    grid = [POSITIONS[i:i + 3] for i in range(0, 9, 3)]
    rows = [
        [btn(("✅" if pos == current else POSITION_ICONS[pos]), Cs(a="wm_pos", c=channel.id, p=post_id, v=pos)) for pos in row]
        for row in grid
    ]
    rows.append([btn(t("btn.back"), Cs(a="wm", c=channel.id, p=post_id))])
    return t("wm.position_title"), markup(rows)


def sig_menu(
    channel: Channel, post: Post | None, *, can_settings: bool = True, can_templates: bool = True,
) -> tuple[str, InlineKeyboardMarkup]:
    """`can_templates` — may add and delete the extra templates (the owner and admins with posts or settings rights)."""
    p = post.id if post else 0
    c = channel.id
    templates = signature_templates(channel)
    ids = [tid for tid, _ in templates]
    chosen = options_of(post)["signature_tpl"] if post is not None else 0
    chosen = chosen if chosen in ids else 0
    lines = [t("sig.title", title=html.escape(channel.title)), ""]
    if len(templates) == 1:
        lines += [t("sig.preview"), render_signature(channel), "", t("sig.template", template=html.escape(templates[0][1]))]
    else:
        for n, (tid, template) in enumerate(templates, 1):
            head = t("sig.item_main", n=n) if tid == 0 else t("sig.item", n=n)
            if post is not None and tid == chosen:
                head += " ✅"
            lines += [head, render_signature(channel, tid)]
            if post is None:  # the raw template is for the channel card; the post editor shows just the signatures
                lines.append(f"<code>{html.escape(template)}</code>")
            lines.append("")
        lines.pop()
    if post is None:
        lines += ["", t("sig.help")]
    rows = []
    if post is not None:
        rows.append([btn(on(options_of(post)["signature"]) + t("sig.apply_post"), Cs(a="sig_post", c=c, p=p))])
        if len(templates) > 1:
            rows += [[btn(("✅ " if tid == chosen else "") + sig_label(channel, tid, n), Cs(a="sig_pick", c=c, p=p, v=str(tid)))]
                     for n, (tid, _) in enumerate(templates, 1)]
    if post is None:  # managing the templates is for the channel card; the post editor only picks one
        rights = {"can_settings": can_settings, "can_templates": can_templates}
        if sig_editable(templates, rights):
            rows.append([btn(t("sig.edit"), Cs(a="sig_edit", c=c, p=p))])
        if can_settings and channel.signature_template:
            rows.append([btn(t("sig.reset"), Cs(a="sig_reset", c=c, p=p))])
        if can_templates and len(templates) < MAX_SIGNATURE_TEMPLATES:
            rows.append([btn(t("sig.add"), Cs(a="sig_add", c=c, p=p))])
        deletable = sig_deletable(templates, rights)
        rows += [[btn("🗑 " + sig_label(channel, tid, n), Cs(a="sig_del", c=c, p=p, v=str(tid)))]
                 for n, (tid, _) in enumerate(templates, 1) if tid in deletable]
        if can_settings:
            rows.append([btn(on(channel.signature_on) + t("sig.default_toggle"), Cs(a="sig_def", c=c, p=p))])
    rows.append([back_button(channel, p)])
    return "\n".join(lines), markup(rows)


def sig_label(channel: Channel, template_id: int, n: int) -> str:
    """A button label for a template: the signature itself as plain text, so it's clear which one it is."""
    return snippet(render_signature(channel, template_id), 50) or t("sig.pick", n=n)


def sig_editable(templates: list[tuple[int, str]], rights: dict) -> list[int]:
    """Template ids `rights` may change: the main one needs settings rights, the extra ones posts or settings."""
    return [tid for tid, _ in templates if rights["can_settings" if tid == 0 else "can_templates"]]


def sig_deletable(templates: list[tuple[int, str]], rights: dict) -> list[int]:
    """Like sig_editable, but there is always one template left: the main one goes only while there are others."""
    return [tid for tid in sig_editable(templates, rights) if tid != 0 or len(templates) > 1]


async def sig_rights(session: AsyncSession, channel: Channel, user: User) -> dict:
    """sig_menu's keyword arguments for `user`."""
    if channel.owner_id == user.id:
        return {"can_settings": True, "can_templates": True}
    can_settings = await channel_admins_repo.has_permission(session, channel.id, user.id, "settings")
    can_posts = await channel_admins_repo.has_permission(session, channel.id, user.id, "posts")
    return {"can_settings": can_settings, "can_templates": can_settings or can_posts}


def cm_menu(channel: Channel) -> tuple[str, InlineKeyboardMarkup]:
    c = channel.id
    mod = moderation_settings(channel.moderation)
    lines = [t("cm.title", title=html.escape(channel.title))]
    if channel.discussion_chat_id:
        lines += ["", t("cm.linked", title=html.escape(channel.discussion_title or ""))]
    else:
        lines += ["", t("cm.not_linked")]
    lines += [
        "", t("cm.moderation_on") if mod["enabled"] else t("cm.moderation_off"),
        t("cm.banned_words_count", n=len(mod["banned_words"])),
    ]
    lines.append(t("cm.aimod_on") if mod["ai"] else t("cm.aimod_off"))
    if mod["ai"] and mod["ai_out"]:
        lines.append(t("cm.aimod_paused"))
    auto = auto_comment_settings(channel.auto_comment)
    lines += ["", t("cm.auto_on") if auto["enabled"] else t("cm.auto_off")]
    if auto["enabled"]:
        lines += [t("cm.auto_preview"), auto["html"]]
    lines += ["", t("cm.help")]
    if channel.discussion_chat_id:
        rows = [[btn(t("cm.relink"), Cs(a="cm_link", c=c)), btn(t("cm.unlink"), Cs(a="cm_unlink", c=c))]]
    else:
        rows = [[btn(t("cm.link"), Cs(a="cm_link", c=c))]]
    rows.append([
        btn(on(mod["enabled"]) + t("cm.moderation_toggle"), Cs(a="mod_t", c=c)),
        btn(t("cm.banned_words_btn"), Cs(a="mod_words", c=c)),
    ])
    rows.append([btn(on(mod["ai"]) + t("cm.aimod_btn"), Px(a="aimod", c=c, v="cm"))])
    rows.append([
        btn(on(auto["enabled"]) + t("cm.auto_btn"), Cs(a="ac_t", c=c)),
        btn(t("cm.auto_text_btn"), Cs(a="ac_text", c=c)),
    ])
    rows.append([back_button(channel, 0)])
    return "\n".join(lines), markup(rows)


async def stats_view(session: AsyncSession, channel: Channel, user: User, days: int) -> tuple[str, InlineKeyboardMarkup]:
    now = utcnow()
    since = now - timedelta(days=days)
    # +1s guards against a post published this same instant: `published_between`'s upper bound is exclusive.
    pubs = await pubs_repo.published_between(session, user.id, since, now + timedelta(seconds=1), channel_ids=[channel.id])
    lines = [t("stats.title", title=html.escape(channel.title)), "", t("stats.summary",
              count=len(pubs), reactions=sum(reactions_total(p) for p in pubs),
              comments=sum(p.comments_count or 0 for p in pubs))]
    top = sorted(pubs, key=engagement_score, reverse=True)[:STATS_TOP_N]
    lines += ["", t("stats.top_title")]
    if not top:
        lines.append(t("stats.empty"))
    for i, pub in enumerate(top, 1):
        post = await posts_repo.get_post(session, pub.owner_id, pub.post_id)
        title = snippet(part_preview_text(post.parts[0]), 40) if post and post.parts else ""
        title = html.escape(title) if title else t("stats.no_text")
        ids = publication_message_ids(pub)
        row = t("stats.row", n=i, title=title, reactions=reactions_total(pub), comments=pub.comments_count or 0)
        lines.append(f'<a href="{message_link(channel, ids[0])}">{row}</a>' if ids else row)
    rows = [[
        btn(("✅ " if days == d else "") + t(f"stats.period_{d}"), Cs(a="stats", c=channel.id, v=str(d)))
        for d in STATS_PERIODS
    ], [back_button(channel, 0)]]
    return "\n".join(lines), markup(rows)


async def _edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None, *, no_preview: bool = False) -> None:
    if cb.message is None:
        return
    preview = LinkPreviewOptions(is_disabled=True) if no_preview else None
    try:
        await cb.message.edit_text(text, reply_markup=kb, link_preview_options=preview)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await cb.message.answer(text, reply_markup=kb, link_preview_options=preview)


async def _context(
    cb: CallbackQuery, data: Cs, session: AsyncSession, user: User, *, require: str | None = "settings"
) -> tuple[Channel | None, Post | None]:
    """`require` is the delegated-admin permission needed for non-owners (None = any access is enough)."""
    channel = await channels_repo.get_channel(session, user.id, data.c)
    post = await posts_repo.get_post(session, user.id, data.p) if data.p else None
    if channel is None or (data.p and post is None):
        await cb.answer(t("err.not_found"), show_alert=True)
        return None, None
    if require and channel.owner_id != user.id and not await channel_admins_repo.has_permission(session, channel.id, user.id, require):
        await cb.answer(t("err.not_found"), show_alert=True)
        return None, None
    return channel, post


async def _return_after_input(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher,
    settings: Settings, channel: Channel, note: str,
) -> None:
    data = await state.get_data()
    post_id = data.get("cs_post") or 0
    if post_id:
        post = await posts_repo.get_post(session, user.id, int(post_id))
        if post is not None:
            await state.update_data(post_id=post.id)
            await render_editor(bot, message.chat.id, session, state, user, post, publisher, note=note)
            return
    await state.set_state(None)
    text, kb = channel_card(channel, **await card_kwargs(session, channel, user, settings))
    await message.answer(note + "\n\n" + text, reply_markup=kb)


async def _ask_input(cb: CallbackQuery, state: FSMContext, new_state, channel: Channel, post_id: int, prompt: str) -> None:
    await state.set_state(new_state)
    await state.update_data(cs_channel=channel.id, cs_post=post_id)
    back = Cs(a="wm", c=channel.id, p=post_id) if new_state in (ChannelInput.wm_text, ChannelInput.wm_image) else (
        Cs(a="sig", c=channel.id, p=post_id) if new_state in (ChannelInput.signature, ChannelInput.signature_add) else (
            Ed(a="home", p=post_id) if post_id else Pj(a="ch", c=channel.id)
        )
    )
    await _edit(cb, prompt, markup([[btn(t("btn.back"), back)]]))


async def _input_channel(
    message: Message, session: AsyncSession, state: FSMContext, user: User, perms: tuple[str, ...] = ("settings",),
) -> Channel | None:
    """`perms` — a delegated admin needs any one of these."""
    data = await state.get_data()
    channel = await channels_repo.get_channel(session, user.id, int(data.get("cs_channel") or 0))
    ok = channel is not None and (
        channel.owner_id == user.id
        or any([await channel_admins_repo.has_permission(session, channel.id, user.id, perm) for perm in perms])
    )
    if not ok:
        await state.set_state(None)
        await message.answer(t("err.not_found"))
        return None
    return channel


# ---- callbacks ----------------------------------------------------------------------------------

@router.callback_query(Cs.filter(F.a == "noop"))
async def cs_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(Cs.filter(F.a == "ch"))
async def cs_card(
    cb: CallbackQuery, callback_data: Cs, session: AsyncSession, user: User, settings: Settings
) -> None:
    channel, _ = await _context(cb, callback_data, session, user, require=None)
    if channel is None:
        return
    await cb.answer()
    await _edit(cb, *channel_card(channel, **await card_kwargs(session, channel, user, settings)))


@router.callback_query(Cs.filter(F.a.in_({"notify_def", "notify_rcpt", "gap_t"})))
async def cs_notify(
    cb: CallbackQuery, callback_data: Cs, session: AsyncSession, user: User, settings: Settings
) -> None:
    channel, _ = await _context(cb, callback_data, session, user)
    if channel is None:
        return
    if callback_data.a == "notify_def":
        channel.notify_published = not channel.notify_published
    elif callback_data.a == "gap_t":
        channel.gap_reminder = not channel.gap_reminder
    elif callback_data.v in ("owner", "admin", "both"):
        channel.notify_recipients = callback_data.v
    await session.flush()
    await cb.answer()
    await _edit(cb, *channel_card(channel, **await card_kwargs(session, channel, user, settings)))


@router.callback_query(Cs.filter(F.a == "gap_off"))
async def cs_gap_off(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, user: User) -> None:
    """«Не нагадувати» under a reminder about empty days."""
    channel, _ = await _context(cb, callback_data, session, user)
    if channel is None:
        return
    channel.gap_reminder = False
    await session.flush()
    await cb.answer(t("gap.off_done"), show_alert=True)
    if cb.message is not None:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass


@router.callback_query(Cs.filter(F.a.in_({"wm", "wm_post", "wm_op", "wm_sc", "wm_def", "wm_pos"})))
async def cs_watermark(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, state: FSMContext, user: User) -> None:
    a, v = callback_data.a, callback_data.v
    # Viewing the menu or toggling watermark for one's own post only needs post authoring rights;
    # opacity/scale/position/default-on change the channel-level watermark, so those need "settings".
    require = None if a == "wm" else ("posts" if a == "wm_post" else "settings")
    channel, post = await _context(cb, callback_data, session, user, require=require)
    if channel is None:
        return
    s = wm_settings(channel.watermark)
    if post is not None and cb.message is not None:
        await state.update_data(panel_id=cb.message.message_id, post_id=post.id)
    if a == "wm_post" and post is not None:
        enabled = not options_of(post)["watermark"]
        if enabled and not wm_configured(channel.watermark):
            await cb.answer(t("wm.need_setup"), show_alert=True)
            return
        post.options = {**(post.options or {}), "watermark": enabled}
    elif a == "wm_op":
        s["opacity"] = max(10, min(100, int(s["opacity"]) + int(v)))
    elif a == "wm_sc":
        s["scale"] = max(5, min(90, int(s["scale"]) + int(v)))
    elif a == "wm_def":
        s["enabled"] = not s.get("enabled")
    elif a == "wm_pos" and v in POSITIONS:
        s["position"] = v
    if a in ("wm_op", "wm_sc", "wm_def", "wm_pos"):
        channel.watermark = s
    await session.flush()
    await cb.answer()
    can_settings = channel.owner_id == user.id or await channel_admins_repo.has_permission(session, channel.id, user.id, "settings")
    await _edit(cb, *wm_menu(channel, post, can_settings=can_settings))


@router.callback_query(Cs.filter(F.a == "wm_posm"))
async def cs_wm_position(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, user: User) -> None:
    channel, _ = await _context(cb, callback_data, session, user, require=None)
    if channel is None:
        return
    await cb.answer()
    await _edit(cb, *wm_position_menu(channel, callback_data.p))


@router.callback_query(Cs.filter(F.a == "wm_text"))
async def cs_wm_text(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel, _ = await _context(cb, callback_data, session, user)
    if channel is None:
        return
    await cb.answer()
    await _ask_input(cb, state, ChannelInput.wm_text, channel, callback_data.p, t("wm.text_prompt", max=MAX_WM_TEXT))


@router.callback_query(Cs.filter(F.a == "wm_img"))
async def cs_wm_image(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel, _ = await _context(cb, callback_data, session, user)
    if channel is None:
        return
    await cb.answer()
    await _ask_input(cb, state, ChannelInput.wm_image, channel, callback_data.p, t("wm.image_prompt"))


@router.callback_query(Cs.filter(F.a.in_({"sig", "sig_post", "sig_pick", "sig_del", "sig_reset", "sig_def"})))
async def cs_signature(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, state: FSMContext, user: User) -> None:
    a = callback_data.a
    # Viewing the menu or toggling/picking the signature for one's own post only needs post authoring rights;
    # deleting an extra template is checked below (posts or settings); resetting the main template or flipping
    # the channel default changes channel-level config.
    require = None if a in ("sig", "sig_del") else ("posts" if a in ("sig_post", "sig_pick") else "settings")
    channel, post = await _context(cb, callback_data, session, user, require=require)
    if channel is None:
        return
    rights = await sig_rights(session, channel, user)
    if a == "sig_del" and not (
        callback_data.v.isdigit() and int(callback_data.v) in sig_deletable(signature_templates(channel), rights)
    ):
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    if post is not None and cb.message is not None:
        await state.update_data(panel_id=cb.message.message_id, post_id=post.id)
    if a == "sig_post" and post is not None:
        post.options = {**(post.options or {}), "signature": not options_of(post)["signature"]}
    elif a == "sig_pick" and post is not None and callback_data.v.isdigit():
        post.options = {**(post.options or {}), "signature": True, "signature_tpl": int(callback_data.v)}
    elif a == "sig_del" and callback_data.v == "0":
        # The next template becomes the main one; posts that picked it fall back to the main one — the same text.
        first, *rest = channel.signature_extra
        channel.signature_template = first["html"]
        channel.signature_extra = rest
    elif a == "sig_del":
        channel.signature_extra = [x for x in (channel.signature_extra or []) if int(x["id"]) != int(callback_data.v)]
    elif a == "sig_reset":
        channel.signature_template = None
    elif a == "sig_def":
        channel.signature_on = not channel.signature_on
    await session.flush()
    await cb.answer(t("sig.deleted") if a == "sig_del" else None)
    await _edit(cb, *sig_menu(channel, post, **rights), no_preview=post is not None)


@router.callback_query(Cs.filter(F.a == "sig_edit"))
async def cs_signature_edit(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, state: FSMContext, user: User) -> None:
    """With several templates, first a list to pick which one to change (`v` — its id)."""
    channel, _ = await _context(cb, callback_data, session, user, require=None)
    if channel is None:
        return
    templates = signature_templates(channel)
    editable = sig_editable(templates, await sig_rights(session, channel, user))
    if not editable:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    await cb.answer()
    c, p = channel.id, callback_data.p
    if callback_data.v.isdigit() and int(callback_data.v) in editable:
        tid = int(callback_data.v)
    elif len(templates) == 1:
        tid = 0
    else:
        rows = [[btn("✏️ " + sig_label(channel, i, n), Cs(a="sig_edit", c=c, p=p, v=str(i)))]
                for n, (i, _) in enumerate(templates, 1) if i in editable]
        rows.append([btn(t("btn.back"), Cs(a="sig", c=c, p=p))])
        await _edit(cb, t("sig.edit_pick"), markup(rows))
        return
    n, template = next((n, tpl) for n, (i, tpl) in enumerate(templates, 1) if i == tid)
    prompt = t("sig.prompt") if len(templates) == 1 else (
        t("sig.edit_current", n=n, template=html.escape(template)) + "\n\n" + t("sig.prompt")
    )
    await _ask_input(cb, state, ChannelInput.signature, channel, p, prompt)
    await state.update_data(cs_sig=tid)


@router.callback_query(Cs.filter(F.a == "sig_add"))
async def cs_signature_add(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel, _ = await _context(cb, callback_data, session, user, require=None)
    if channel is None:
        return
    if not (await sig_rights(session, channel, user))["can_templates"]:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    if len(signature_templates(channel)) >= MAX_SIGNATURE_TEMPLATES:
        await cb.answer(t("sig.too_many", max=MAX_SIGNATURE_TEMPLATES), show_alert=True)
        return
    await cb.answer()
    await _ask_input(cb, state, ChannelInput.signature_add, channel, callback_data.p, t("sig.add_prompt"))


@router.callback_query(Cs.filter(F.a.in_({"ai_style", "ai_style_reset"})))
async def cs_ai_style(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel, _ = await _context(cb, callback_data, session, user)
    if channel is None:
        return
    if callback_data.a == "ai_style_reset":
        channel.ai_style_prompt = None
        await session.flush()
        await cb.answer(t("ai.style_reset_done"))
    else:
        await cb.answer()
    current = html.escape(channel.ai_style_prompt) if channel.ai_style_prompt else t("ai.style_none")
    prompt = t("ai.style_prompt", current=current, max=MAX_STYLE)
    await state.set_state(ChannelInput.ai_style)
    await state.update_data(cs_channel=channel.id, cs_post=callback_data.p)
    back = Ed(a="ai", p=callback_data.p) if callback_data.p else Pj(a="ch", c=channel.id)
    rows = [[btn(t("ai.style_reset"), Cs(a="ai_style_reset", c=channel.id, p=callback_data.p))]] if channel.ai_style_prompt else []
    rows.append([btn(t("btn.back"), back)])
    await _edit(cb, prompt, markup(rows))


@router.callback_query(Cs.filter(F.a.in_({"topic", "topic_general"})))
async def cs_topic(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel, _ = await _context(cb, callback_data, session, user)
    if channel is None:
        return
    if callback_data.a == "topic_general":
        channel.topic_id = 0
        await session.flush()
        await cb.answer(t("topic.saved_general"))
        await _edit(cb, t("topic.saved_general"), None)
        return
    await cb.answer()
    await _ask_input(cb, state, ChannelInput.topic, channel, callback_data.p, t("topic.prompt"))


@router.callback_query(Cs.filter(F.a == "stats"))
async def cs_stats(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, user: User) -> None:
    channel, _ = await _context(cb, callback_data, session, user, require="posts")
    if channel is None:
        return
    days = int(callback_data.v) if callback_data.v.isdigit() and int(callback_data.v) in STATS_PERIODS else STATS_PERIODS[0]
    await cb.answer()
    await _edit(cb, *await stats_view(session, channel, user, days))


@router.callback_query(Cs.filter(F.a.in_({"cm", "cm_unlink"})))
async def cs_comments(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, user: User) -> None:
    channel, _ = await _context(cb, callback_data, session, user)
    if channel is None:
        return
    if callback_data.a == "cm_unlink":
        channel.discussion_chat_id = None
        channel.discussion_title = None
    await session.flush()
    await cb.answer()
    await _edit(cb, *cm_menu(channel))


@router.callback_query(Cs.filter(F.a == "cm_link"))
async def cs_comments_link(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel, _ = await _context(cb, callback_data, session, user)
    if channel is None:
        return
    await cb.answer()
    await state.set_state(ChannelInput.discussion_group)
    await state.update_data(cs_channel=channel.id, cs_post=callback_data.p)
    if cb.message:
        await cb.message.answer(t("cm.link_prompt"), reply_markup=link_discussion_kb())


@router.callback_query(Cs.filter(F.a == "mod_t"))
async def cs_moderation_toggle(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, user: User) -> None:
    channel, _ = await _context(cb, callback_data, session, user)
    if channel is None:
        return
    mod = moderation_settings(channel.moderation)
    channel.moderation = {**mod, "enabled": not mod["enabled"]}
    await session.flush()
    await cb.answer()
    await _edit(cb, *cm_menu(channel))


@router.callback_query(Cs.filter(F.a == "mod_words"))
async def cs_moderation_words(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel, _ = await _context(cb, callback_data, session, user)
    if channel is None:
        return
    await cb.answer()
    mod = moderation_settings(channel.moderation)
    current = ", ".join(mod["banned_words"]) if mod["banned_words"] else t("mod.words_none")
    await state.set_state(ChannelInput.banned_words)
    await state.update_data(cs_channel=channel.id, cs_post=callback_data.p)
    rows = [[btn(t("btn.back"), Cs(a="cm", c=channel.id, p=callback_data.p))]]
    await _edit(cb, t("mod.words_prompt", current=html.escape(current), max=MAX_BANNED_WORDS), markup(rows))


@router.callback_query(Cs.filter(F.a == "ac_t"))
async def cs_auto_comment_toggle(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, user: User) -> None:
    channel, _ = await _context(cb, callback_data, session, user)
    if channel is None:
        return
    s = auto_comment_settings(channel.auto_comment)
    if not s["enabled"] and not channel.discussion_chat_id:
        await cb.answer(t("cm.auto_need_group"), show_alert=True)
        return
    channel.auto_comment = {**s, "enabled": not s["enabled"], "html": s["html"] or t("cm.auto_default")}
    await session.flush()
    await cb.answer()
    await _edit(cb, *cm_menu(channel))


@router.callback_query(Cs.filter(F.a == "ac_text"))
async def cs_auto_comment_text(cb: CallbackQuery, callback_data: Cs, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel, _ = await _context(cb, callback_data, session, user)
    if channel is None:
        return
    await cb.answer()
    await state.set_state(ChannelInput.auto_comment)
    await state.update_data(cs_channel=channel.id, cs_post=0)
    rows = [[btn(t("btn.back"), Cs(a="cm", c=channel.id))]]
    await _edit(cb, t("cm.auto_prompt", max=MAX_AUTO_COMMENT), markup(rows))


# ---- text/file inputs ---------------------------------------------------------------------------

@router.message(ChannelInput.wm_text, F.text)
async def in_wm_text(message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher,
                   settings: Settings) -> None:
    channel = await _input_channel(message, session, state, user)
    if channel is None:
        return
    text = (message.text or "").strip()
    if not text or len(text) > MAX_WM_TEXT:
        await message.answer(t("wm.text_prompt", max=MAX_WM_TEXT))
        return
    channel.watermark = {**wm_settings(channel.watermark), "type": "text", "text": text, "enabled": True}
    await _enable_for_post(session, state, user)
    await session.flush()
    await _return_after_input(message, bot, session, state, user, publisher, settings, channel, t("wm.saved"))


@router.message(ChannelInput.wm_image, F.photo | F.document)
async def in_wm_image(message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher,
                   settings: Settings) -> None:
    channel = await _input_channel(message, session, state, user)
    if channel is None:
        return
    if message.document and not (message.document.mime_type or "").startswith("image/"):
        await message.answer(t("wm.image_prompt"))
        return
    file_id = message.document.file_id if message.document else message.photo[-1].file_id
    channel.watermark = {**wm_settings(channel.watermark), "type": "image", "image_file_id": file_id, "enabled": True}
    await _enable_for_post(session, state, user)
    await session.flush()
    await _return_after_input(message, bot, session, state, user, publisher, settings, channel, t("wm.saved"))


async def _enable_for_post(session: AsyncSession, state: FSMContext, user: User) -> None:
    post_id = (await state.get_data()).get("cs_post")
    if post_id:
        post = await posts_repo.get_post(session, user.id, int(post_id))
        if post is not None:
            post.options = {**(post.options or {}), "watermark": True}


def _template_from_message(message: Message) -> str:
    raw = message.text or ""
    if not message.entities and re.search(r"</?(a|b|i|u|s|code)\b", raw):
        return raw.strip()
    return message.html_text.strip()


@router.message(ChannelInput.signature, F.text)
async def in_signature(message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher,
                   settings: Settings) -> None:
    channel = await _input_channel(message, session, state, user, perms=("settings", "posts"))
    if channel is None:
        return
    data = await state.get_data()
    tid = int(data.get("cs_sig") or 0)
    if tid not in sig_editable(signature_templates(channel), await sig_rights(session, channel, user)):
        await state.set_state(None)
        await message.answer(t("err.not_found"))
        return
    template = _template_from_message(message)
    if not template or visible_len(template) > MAX_SIGNATURE:
        await message.answer(t("sig.prompt"))
        return
    old_main, old_extra = channel.signature_template, list(channel.signature_extra or [])
    if tid == 0:
        channel.signature_template = template
    else:
        channel.signature_extra = [{**x, "html": template} if int(x["id"]) == tid else x for x in old_extra]
    if not sanitize_html(render_signature(channel, tid)):
        channel.signature_template, channel.signature_extra = old_main, old_extra
        await message.answer(t("sig.invalid"))
        return
    post_id = data.get("cs_post")
    if post_id:
        post = await posts_repo.get_post(session, user.id, int(post_id))
        if post is not None:
            post.options = {**(post.options or {}), "signature": True, "signature_tpl": tid}
    await session.flush()
    await _after_sig_input(message, bot, session, state, user, publisher, settings, channel, t("sig.saved"))


async def _after_sig_input(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher,
    settings: Settings, channel: Channel, note: str,
) -> None:
    """Back to the post editor, or — from «Мої проєкти» — to the «Автопідпис» menu to see all the templates."""
    if (await state.get_data()).get("cs_post"):
        await _return_after_input(message, bot, session, state, user, publisher, settings, channel, note)
        return
    await state.set_state(None)
    text, kb = sig_menu(channel, None, **await sig_rights(session, channel, user))
    await message.answer(note + "\n\n" + text, reply_markup=kb, disable_web_page_preview=True)


@router.message(ChannelInput.signature_add, F.text)
async def in_signature_add(message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
                           publisher: Publisher, settings: Settings) -> None:
    channel = await _input_channel(message, session, state, user, perms=("settings", "posts"))
    if channel is None:
        return
    template = _template_from_message(message)
    if not template or visible_len(template) > MAX_SIGNATURE:
        await message.answer(t("sig.add_prompt"))
        return
    templates = signature_templates(channel)
    if len(templates) >= MAX_SIGNATURE_TEMPLATES:
        await state.set_state(None)
        await message.answer(t("sig.too_many", max=MAX_SIGNATURE_TEMPLATES))
        return
    new_id = max(tid for tid, _ in templates) + 1
    channel.signature_extra = [*(channel.signature_extra or []), {"id": new_id, "html": template}]
    if not sanitize_html(render_signature(channel, new_id)):
        channel.signature_extra = channel.signature_extra[:-1]
        await message.answer(t("sig.invalid"))
        return
    post_id = (await state.get_data()).get("cs_post")
    if post_id:
        post = await posts_repo.get_post(session, user.id, int(post_id))
        if post is not None:
            post.options = {**(post.options or {}), "signature": True, "signature_tpl": new_id}
    await session.flush()
    await _after_sig_input(message, bot, session, state, user, publisher, settings, channel, t("sig.added"))


@router.message(ChannelInput.ai_style, F.text)
async def in_ai_style(message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher,
                   settings: Settings) -> None:
    channel = await _input_channel(message, session, state, user)
    if channel is None:
        return
    text = (message.text or "").strip()
    if not text or len(text) > MAX_STYLE:
        await message.answer(t("ai.style_prompt", current="—", max=MAX_STYLE))
        return
    channel.ai_style_prompt = text
    await session.flush()
    await _return_after_input(message, bot, session, state, user, publisher, settings, channel, t("ai.style_saved"))


@router.message(ChannelInput.topic, F.text)
async def in_topic(message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher,
                   settings: Settings) -> None:
    channel = await _input_channel(message, session, state, user)
    if channel is None:
        return
    try:
        ref = parse_topic(message.text or "")
    except ParseError as e:
        await message.answer(t(e.key))
        return
    channel.topic_id = ref.topic_id
    await session.flush()
    await _return_after_input(message, bot, session, state, user, publisher, settings, channel, t("topic.saved", topic=ref.topic_id))


@router.message(ChannelInput.banned_words, F.text)
async def in_banned_words(message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher,
                   settings: Settings) -> None:
    channel = await _input_channel(message, session, state, user)
    if channel is None:
        return
    words = [w.strip() for w in re.split(r"[,\n]", message.text or "") if w.strip()]
    if len(words) > MAX_BANNED_WORDS:
        await message.answer(t("mod.words_too_many", max=MAX_BANNED_WORDS))
        return
    mod = moderation_settings(channel.moderation)
    channel.moderation = {**mod, "banned_words": words}
    await session.flush()
    await _return_after_input(message, bot, session, state, user, publisher, settings, channel, t("mod.words_saved", n=len(words)))


@router.message(ChannelInput.auto_comment, F.text)
async def in_auto_comment(message: Message, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel = await _input_channel(message, session, state, user)
    if channel is None:
        return
    text = sanitize_html(_template_from_message(message))
    if not text or visible_len(text) > MAX_AUTO_COMMENT:
        await message.answer(t("cm.auto_prompt", max=MAX_AUTO_COMMENT))
        return
    channel.auto_comment = {**auto_comment_settings(channel.auto_comment), "html": text, "enabled": True}
    await session.flush()
    await state.set_state(None)
    view, kb = cm_menu(channel)
    await message.answer(t("cm.auto_saved") + "\n\n" + view, reply_markup=kb, disable_web_page_preview=True)


@router.message(ChannelInput.wm_image)
@router.message(ChannelInput.wm_text)
@router.message(ChannelInput.signature)
@router.message(ChannelInput.signature_add)
@router.message(ChannelInput.ai_style)
@router.message(ChannelInput.topic)
@router.message(ChannelInput.auto_comment)
async def in_wrong(message: Message) -> None:
    await message.answer(t("err.expected_input"))
