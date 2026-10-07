"""«Налаштування реклами»: an ad's format, pin, delete timer, sound, comments, the post it answers, its booking,
the AI vetting of the ad and the report on it for the advertiser."""
from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.defaults import done_screen
from flowpost.bot.handlers.editor.view import load_editor_post, post_from_callback, render_editor, show_panel
from flowpost.bot.keyboards.common import btn, chunked, markup
from flowpost.bot.states import Editor
from flowpost.config import Settings
from flowpost.db.models import Post, User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services import ads, analytics, pro_ai
from flowpost.services.ai import AIError, AIService
from flowpost.services.billing import entitlements
from flowpost.services.pro_ai import ProAIError
from flowpost.services.posts import AD_FORMATS, message_link, options_of, post_is_empty
from flowpost.services.publisher import Publisher

router = Router(name="editor_ad")

TOGGLES = {"link_preview", "silent", "comments"}
DELETE_CHOICES = (6, 12, 24, 48, 72)
MAX_HOURS = 720


async def _redraw(bot: Bot, chat_id: int, session: AsyncSession, state: FSMContext, user: User, post: Post,
                  publisher: Publisher, note: str | None = None) -> None:
    await render_editor(bot, chat_id, session, state, user, post, publisher, note=note, preview=False)


def _set(post: Post, **changes) -> None:
    post.options = {**(post.options or {}), **changes}


@router.callback_query(Ed.filter(F.a.in_({"ad_t", "ad_fmt", "ad_pin", "ad_delv"})))
async def ed_ad_option(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    opts = options_of(post)
    a, v = callback_data.a, callback_data.v
    if a == "ad_t" and v in TOGGLES:
        _set(post, **{v: not opts[v]})
    elif a == "ad_fmt" and v.isdigit() and int(v) in AD_FORMATS:
        n = int(v)
        if opts["ad_format"] == n:
            _set(post, ad_format=None, auto_delete_hours=None)
        else:
            _set(post, ad_format=n, auto_delete_hours=AD_FORMATS[n][1])
    elif a == "ad_pin":
        _set(post, pin=v == "1", pin_hours=None)
    elif a == "ad_delv":
        hours = int(v) if v.isdigit() else None
        fmt = AD_FORMATS.get(opts["ad_format"] or 0)
        _set(post, auto_delete_hours=hours or None, **({} if fmt and fmt[1] == hours else {"ad_format": None}))
    await session.flush()
    await cb.answer()
    await _redraw(bot, cb.from_user.id, session, state, user, post, publisher)


@router.callback_query(Ed.filter(F.a.in_({"ad_del", "ad_delc"})))
async def ed_ad_delete(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    p = post.id
    if callback_data.a == "ad_delc":
        await state.set_state(Editor.delete_hours)
        back = markup([[btn(t("ad.back"), Ed(a="ad_del", p=p))]])
        await show_panel(bot, cb.from_user.id, state, t("more.delete_prompt", max=MAX_HOURS), back)
        return
    await state.set_state(Editor.content)
    hours = options_of(post)["auto_delete_hours"]
    rows = chunked([
        btn(("🔘 " if hours == h else "") + t("ad.hours", hours=h), Ed(a="ad_delv", p=p, v=str(h)))
        for h in DELETE_CHOICES
    ], 3)
    rows.append([btn(t("more.custom"), Ed(a="ad_delc", p=p)), btn(t("ad.delete_never"), Ed(a="ad_delv", p=p, v="0"))])
    rows.append([btn(t("ad.back"), Ed(a="home", p=p))])
    await show_panel(bot, cb.from_user.id, state, t("ad.delete_title"), markup(rows))


@router.callback_query(Ed.filter(F.a == "ad_reply"))
async def ed_ad_reply(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    if options_of(post)["reply_to"]:
        _set(post, reply_to=None)
        await session.flush()
        await cb.answer(t("ad.reply_removed"))
        await _redraw(bot, cb.from_user.id, session, state, user, post, publisher)
        return
    await cb.answer()
    await state.set_state(Editor.ad_reply)
    back = markup([[btn(t("ad.back"), Ed(a="home", p=post.id))]])
    await show_panel(bot, cb.from_user.id, state, t("ad.reply_prompt"), back)


@router.message(Editor.ad_reply)
async def in_ad_reply(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher
) -> None:
    post, _ = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
    found = None
    origin = message.forward_origin
    chat = getattr(origin, "chat", None)
    if chat is not None and getattr(origin, "message_id", None):
        channel = next((c for c in channels if c.chat_id == chat.id), None)
        found = (channel, origin.message_id) if channel else None
    else:
        found = ads.parse_post_link(message.text or "", channels)
    if found is None:
        await message.answer(t("ad.reply_wrong"))
        return
    channel, message_id = found
    _set(post, reply_to={"ch": channel.id, "msg": message_id, "url": message_link(channel, message_id)})
    await session.flush()
    await render_editor(bot, message.chat.id, session, state, user, post, publisher, note=t("ad.reply_saved"))


@router.callback_query(Ed.filter(F.a == "ad_ok"))
async def ed_ad_confirm(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    """Confirm a booked slot: the ad is there and paid, so it goes out at its time."""
    in_editor = await state.get_state() is not None
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    if not ads.is_booking(post):
        await cb.answer(t("ad.confirmed"))
        return
    if post_is_empty(post):
        await cb.answer(t("ad.confirm_empty"), show_alert=True)
        return
    _set(post, ad_booking=False)
    await session.flush()
    await cb.answer(t("ad.confirmed"))
    if in_editor:
        await _redraw(bot, cb.from_user.id, session, state, user, post, publisher, note="✅ " + t("ad.confirmed"))
        return
    # From the «Готово» screen of a scheduled booking: the editor is closed, so only that message changes.
    await state.clear()
    text, kb = await done_screen(session, user, post)
    if cb.message is not None:
        await cb.message.edit_text(text, reply_markup=kb)


# ---- 🛡 vetting the ad ----------------------------------------------------------------------------------------------

CHECK_ICONS = {"scam": "🚨", "forbidden": "⛔", "misleading": "🎭", "links": "🔗", "topic": "🎯", "quality": "✏️"}


def check_view(post: Post, check: dict) -> tuple[str, object]:
    report = check["report"]
    lines = [t("adchk.title"), "", t(f"adchk.verdict_{report['verdict']}")]
    if report["category"]:
        lines.append(t("adchk.category", text=html.escape(report["category"], quote=False)))
    if report["summary"]:
        lines += ["", html.escape(report["summary"], quote=False)]
    if report["issues"]:
        lines.append("")
        lines += [f"{CHECK_ICONS.get(i['kind'], '•')} {html.escape(i['note'], quote=False)}" for i in report["issues"]]
    if check.get("links"):
        lines += ["", t("adchk.links")]
        for url, status in check["links"]:
            ok = status.split("; ")[-1].startswith("opens")
            lines.append(f"{'✅' if ok else '❌'} {html.escape(url)}")
    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3900].rsplit("\n", 1)[0] + "\n…"
    kb = markup([
        [btn(t("adchk.again"), Ed(a="ad_chk", p=post.id, v="again"))],
        [btn(t("ad.back"), Ed(a="home", p=post.id))],
    ])
    return text, kb


@router.callback_query(Ed.filter(F.a == "ad_chk"))
async def ed_ad_check(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    settings: Settings, ai: AIService,
) -> None:
    """One AI text per check; the result is kept with the ad, so looking at it again is free until the ad changes."""
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    if post_is_empty(post):
        await cb.answer(t("adchk.empty"), show_alert=True)
        return
    current = ads.content_hash(post)
    cached = options_of(post)["ad_check"]
    if cached and cached.get("hash") == current and callback_data.v != "again":
        await cb.answer()
        await state.set_state(Editor.content)
        await show_panel(bot, cb.from_user.id, state, *check_view(post, cached))
        return
    channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
    if not channels:
        await cb.answer(t("post.no_channels"), show_alert=True)
        return
    channel = channels[0]
    back = markup([[btn(t("ad.back"), Ed(a="home", p=post.id))]])
    try:
        if not ai.enabled:
            raise ProAIError("ai.disabled")
        await pro_ai.spend(session, settings, user, channel)
    except ProAIError as e:
        await cb.answer(t(e.key), show_alert=True)
        return
    await cb.answer()
    await state.set_state(Editor.content)
    await show_panel(bot, cb.from_user.id, state, t("adchk.working"), None)
    links = await ads.check_links(post)
    text = "\n\n".join(part.text_html for part in post.parts if part.text_html.strip())
    buttons = [f"[{b['text']}]" for part in post.parts for row in part.buttons or [] for b in row]
    if buttons:
        text += "\n\n" + " ".join(buttons)
    try:
        report = await ai.check_ad(text, links, channel_title=channel.title, lang=user.lang, style=channel.ai_style_prompt)
    except AIError as e:
        await pro_ai.refund(session, channel.id)
        await show_panel(bot, cb.from_user.id, state, t(e.key), back)
        return
    analytics.track(session, user.id, "ai_call", action="ad_check")
    check = {"hash": current, "report": report, "links": links}
    _set(post, ad_check=check)
    await session.flush()
    await show_panel(bot, cb.from_user.id, state, *check_view(post, check))


# ---- 📊 the report for the advertiser -------------------------------------------------------------------------------

@router.callback_query(Ed.filter(F.a == "ad_rep"))
async def ed_ad_report(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    turn_on = not options_of(post)["ad_report"]
    if turn_on:
        channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
        if not await entitlements.extras_allowed(session, channels, utcnow()):
            await cb.answer(t("paywall.extras_short"), show_alert=True)
            return
    _set(post, ad_report=turn_on)
    await session.flush()
    await cb.answer(t("adrep.on") if turn_on else t("adrep.off"), show_alert=turn_on)
    await _redraw(bot, cb.from_user.id, session, state, user, post, publisher)
