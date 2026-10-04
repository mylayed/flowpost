"""«⭐ PRO-інструменти» of a channel: tracked ad links, join requests, RSS sources, the AI content plan, the idea
bank, translation for multiposting and the weekly report. They work while the channel is on a paid plan or trial.
Giveaways (among commenters, or with a «Беру участь» button) live here too, but they are free for every channel."""
from __future__ import annotations

import html
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Cs, Pj, Px
from flowpost.bot.handlers.channel_settings import cm_menu
from flowpost.bot.handlers.editor.publish import publish_now
from flowpost.bot.handlers.editor.schedule import show_schedule
from flowpost.bot.handlers.editor.view import open_editor
from flowpost.bot.keyboards.common import btn, chunked, markup, on, paywall_kb
from flowpost.bot.states import ProInput
from flowpost.config import Settings
from flowpost.db.models import Channel, Commenter, Feed, Giveaway, InviteLink, Post, Publication, User
from flowpost.db.repo import channel_admins as channel_admins_repo
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.db.repo import publications as pubs_repo
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services import giveaway, growth, pro_ai, rss
from flowpost.services import ideas as ideas_service
from flowpost.services.ai import LANG_NAMES, AIService
from flowpost.services.billing import entitlements, limits
from flowpost.services.delivery import publication_message_ids
from flowpost.services.html_sanitize import snippet
from flowpost.services.moderation import moderation_settings
from flowpost.services.posts import initial_options, message_link, part_preview_text
from flowpost.services.publisher import Publisher
from flowpost.services.slots import tz_of
from flowpost.services.worker import Worker

router = Router(name="pro")

MAX_FEEDS = 10
GIVEAWAY_POSTS = 10
LANG_FLAGS = {"uk": "🇺🇦", "en": "🇬🇧", "pl": "🇵🇱", "de": "🇩🇪", "es": "🇪🇸", "fr": "🇫🇷", "it": "🇮🇹", "pt": "🇵🇹"}


# ---- helpers ------------------------------------------------------------------------------------

async def _edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None) -> None:
    if cb.message is None:
        return
    try:
        await cb.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await cb.message.answer(text, reply_markup=kb, disable_web_page_preview=True)


async def _allowed(session: AsyncSession, user: User, channel_id: int) -> Channel | None:
    """The channel, if `user` owns it or may change its settings."""
    channel = await channels_repo.get_channel(session, user.id, channel_id)
    if channel is None:
        return None
    if channel.owner_id != user.id and not await channel_admins_repo.has_permission(session, channel.id, user.id, "settings"):
        return None
    return channel


async def _extras(session: AsyncSession, settings: Settings, channel: Channel) -> bool:
    owner = await session.get(User, channel.owner_id)
    return owner is not None and entitlements.has_extras(
        await entitlements.for_channel(session, settings, channel, owner, utcnow())
    )


async def _channel(
    cb: CallbackQuery, data: Px, session: AsyncSession, user: User, settings: Settings, *, paid: bool = True,
) -> Channel | None:
    """The channel of the tap, or None after telling the user why not (no access, or not on a paid plan/trial)."""
    channel = await _allowed(session, user, data.c)
    if channel is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return None
    if paid and not await _extras(session, settings, channel):
        await cb.answer(t("paywall.extras_short"), show_alert=True)
        if cb.message is not None:
            await cb.message.answer(t("pro.paywall"), reply_markup=paywall_kb(settings))
        return None
    return channel


def _back(channel: Channel, to: str = "menu") -> list:
    return [btn(t("btn.back"), Px(a=to, c=channel.id))]


def _approve_label(value: str) -> str:
    return t(f"jr.approve_{value}") if value in ("off", "now") else t("jr.approve_after", minutes=_minutes(int(value)))


def _minutes(n: int) -> str:
    if n % 1440 == 0:
        return t("fmt.days", n=n // 1440)
    if n % 60 == 0:
        return t("fmt.hours", n=n // 60)
    return t("fmt.minutes", n=n)


def _money(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


# ---- menu ---------------------------------------------------------------------------------------

async def pro_menu(session: AsyncSession, settings: Settings, channel: Channel) -> tuple[str, InlineKeyboardMarkup]:
    c = channel.id
    feeds = await session.scalar(select(func.count(Feed.id)).where(Feed.channel_id == c)) or 0
    links = len(await growth.channel_links(session, c))
    ideas = len(await ideas_service.for_channel(session, channel))
    lines = [t("pro.title", title=html.escape(channel.title)), "", t("pro.help")]
    if not await _extras(session, settings, channel):
        lines += ["", t("pro.locked")]
    lang = channel.translate_lang
    ai_mod = moderation_settings(channel.moderation)["ai"]
    checks_left = (await limits.remaining(session, c))["ai_mod"]
    answerer = pro_ai.tools_settings(channel.ai_tools)["answer"]
    rows = [
        [btn(t("pro.links") + (f" ({links})" if links else ""), Px(a="links", c=c))],
        [btn(t("pro.rss") + (f" ({feeds})" if feeds else ""), Px(a="rss", c=c))],
        [btn(t("pro.plan"), Px(a="plan", c=c))],
        [btn(t("pro.ideas") + (f" ({ideas})" if ideas else ""), Px(a="ideas", c=c))],
        [btn(t("pro.translate", lang=(LANG_FLAGS.get(lang, "") + " " + LANG_NAMES[lang]) if lang in LANG_NAMES
               else t("pro.translate_off")), Px(a="tr", c=c))],
        [btn(on(channel.weekly_report) + t("pro.report"), Px(a="rep_t", c=c))],
        [btn(on(ai_mod) + t("pro.aimod", n=checks_left), Px(a="aimod", c=c))],
        [btn(t("pro.voice"), Px(a="voice", c=c)), btn(t("pro.adgen"), Px(a="adgen", c=c))],
        [btn(t("pro.niche"), Px(a="niche", c=c))],
        [btn(on(answerer) + t("pro.answer"), Px(a="ans", c=c))],
        [btn(t("btn.back"), Pj(a="ch", c=c))],
    ]
    return "\n".join(lines), markup(rows)


@router.callback_query(Px.filter(F.a.in_({"menu", "rep_t"})))
async def px_menu(cb: CallbackQuery, callback_data: Px, session: AsyncSession, user: User, settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    if channel is None:
        return
    if callback_data.a == "rep_t":
        channel.weekly_report = not channel.weekly_report
        await session.flush()
    await cb.answer()
    await _edit(cb, *await pro_menu(session, settings, channel))


@router.callback_query(Px.filter(F.a == "aimod"))
async def px_ai_moderation(cb: CallbackQuery, callback_data: Px, session: AsyncSession, user: User,
                           settings: Settings) -> None:
    """Toggle AI comment moderation, from the PRO menu or (v="cm") the channel's comments menu."""
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    if channel is None:
        return
    mod = moderation_settings(channel.moderation)
    turning_on = not mod["ai"]
    if turning_on:
        if not channel.discussion_chat_id:
            await cb.answer(t("cm.auto_need_group"), show_alert=True)
            return
        # Turning it off is always allowed; turning it on needs the paid plan or trial.
        if await _channel(cb, callback_data, session, user, settings) is None:
            return
    channel.moderation = {**mod, "ai": turning_on, "enabled": mod["enabled"] or turning_on}
    await session.flush()
    if turning_on:
        await cb.answer(t("aimod.on_done", batch=settings.ai_mod_batch), show_alert=True)
    else:
        await cb.answer()
    if callback_data.v == "cm":
        await _edit(cb, *cm_menu(channel))
    else:
        await _edit(cb, *await pro_menu(session, settings, channel))


@router.callback_query(Px.filter(F.a == "rep_off"))
async def px_report_off(cb: CallbackQuery, callback_data: Px, session: AsyncSession, user: User) -> None:
    """«Вимкнути звіт» under a weekly report."""
    channel = await _allowed(session, user, callback_data.c)
    if channel is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    channel.weekly_report = False
    await session.flush()
    await cb.answer(t("wr.off_done"), show_alert=True)
    if cb.message is not None:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass


# ---- tracked invite links -----------------------------------------------------------------------

async def links_view(session: AsyncSession, channel: Channel) -> tuple[str, InlineKeyboardMarkup]:
    stats = await growth.link_stats(session, await growth.channel_links(session, channel.id))
    lines = [t("lnk.title", title=html.escape(channel.title)), "", t("lnk.help")]
    rows = [[btn(t("lnk.new"), Px(a="lnk_new", c=channel.id))]]
    if stats:
        lines.append("")
    for i, s in enumerate(stats, 1):
        price = t("lnk.row_price", price=_money(s.cost_per_member)) if s.cost_per_member is not None else ""
        lines.append(t("lnk.row", n=i, name=html.escape(s.link.name), joined=s.joined, stayed=s.stayed) + price)
        rows.append([btn(f"{i}. {s.link.name}", Px(a="lnk", c=channel.id, id=s.link.id))])
    rows.append(_back(channel))
    return "\n".join(lines), markup(rows)


async def link_view(session: AsyncSession, channel: Channel, link: InviteLink) -> tuple[str, InlineKeyboardMarkup]:
    s = (await growth.link_stats(session, [link]))[0]
    lines = [
        t("lnk.detail_title", name=html.escape(link.name)),
        f"<code>{html.escape(link.url)}</code>",
        "",
        t("lnk.detail_stats", joined=s.joined, left=s.left, stayed=s.stayed),
    ]
    if link.cost:
        lines.append(t("lnk.detail_cost", cost=_money(link.cost)))
        if s.cost_per_member is not None:
            lines.append(t("lnk.detail_price", price=_money(s.cost_per_member)))
    lines += ["", t("lnk.detail_help")]
    c = channel.id
    rows = [
        [btn(t("lnk.set_cost"), Px(a="lnk_cost", c=c, id=link.id))],
        [btn(t("lnk.revoke"), Px(a="lnk_del", c=c, id=link.id))],
        _back(channel, "links"),
    ]
    return "\n".join(lines), markup(rows)


async def _link(cb: CallbackQuery, session: AsyncSession, channel: Channel, link_id: int) -> InviteLink | None:
    link = await session.get(InviteLink, link_id)
    if link is None or link.channel_id != channel.id or link.revoked:
        await cb.answer(t("err.not_found"), show_alert=True)
        return None
    return link


@router.callback_query(Px.filter(F.a == "links"))
async def px_links(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                   settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    await state.set_state(None)
    await cb.answer()
    await _edit(cb, *await links_view(session, channel))


@router.callback_query(Px.filter(F.a == "lnk"))
async def px_link(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                  settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    link = await _link(cb, session, channel, callback_data.id) if channel else None
    if link is None:
        return
    await state.set_state(None)
    await cb.answer()
    await _edit(cb, *await link_view(session, channel, link))


@router.callback_query(Px.filter(F.a.in_({"lnk_new", "lnk_cost"})))
async def px_link_ask(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                      settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    if callback_data.a == "lnk_new":
        if len(await growth.channel_links(session, channel.id)) >= growth.MAX_LINKS:
            await cb.answer(t("lnk.too_many", max=growth.MAX_LINKS), show_alert=True)
            return
        await state.set_state(ProInput.link_name)
        prompt, back = t("lnk.name_prompt"), _back(channel, "links")
    else:
        if await _link(cb, session, channel, callback_data.id) is None:
            return
        await state.set_state(ProInput.link_cost)
        prompt, back = t("lnk.cost_prompt"), [btn(t("btn.back"), Px(a="lnk", c=channel.id, id=callback_data.id))]
    await state.update_data(px_channel=channel.id, px_link=callback_data.id)
    await cb.answer()
    await _edit(cb, prompt, markup([back]))


async def _input_channel(message: Message, session: AsyncSession, state: FSMContext, user: User) -> Channel | None:
    channel = await _allowed(session, user, int((await state.get_data()).get("px_channel") or 0))
    if channel is None:
        await state.set_state(None)
        await message.answer(t("err.not_found"))
    return channel


@router.message(ProInput.link_name, F.text)
async def in_link_name(message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel = await _input_channel(message, session, state, user)
    if channel is None:
        return
    name = (message.text or "").strip()[:32]
    if not name:
        await message.answer(t("lnk.name_prompt"))
        return
    try:
        invite = await bot.create_chat_invite_link(
            channel.chat_id, name=name, creates_join_request=growth.handles_requests(channel),
        )
    except TelegramAPIError:
        await state.set_state(None)
        await message.answer(t("lnk.err_create"), reply_markup=markup([_back(channel, "links")]))
        return
    link = InviteLink(channel_id=channel.id, name=name, url=invite.invite_link)
    session.add(link)
    await session.flush()
    await state.set_state(None)
    text, kb = await link_view(session, channel, link)
    await message.answer(t("lnk.created") + "\n\n" + text, reply_markup=kb, disable_web_page_preview=True)


@router.message(ProInput.link_cost, F.text)
async def in_link_cost(message: Message, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel = await _input_channel(message, session, state, user)
    if channel is None:
        return
    link = await session.get(InviteLink, int((await state.get_data()).get("px_link") or 0))
    if link is None or link.channel_id != channel.id:
        await state.set_state(None)
        await message.answer(t("err.not_found"))
        return
    raw = re.sub(r"[\s ]", "", (message.text or "")).replace(",", ".")
    raw = re.sub(r"[^\d.]", "", raw)
    try:
        cost = float(raw)
    except ValueError:
        await message.answer(t("lnk.cost_prompt"))
        return
    link.cost = cost if cost > 0 else None
    await session.flush()
    await state.set_state(None)
    text, kb = await link_view(session, channel, link)
    await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(Px.filter(F.a.in_({"lnk_del", "lnk_delok"})))
async def px_link_revoke(cb: CallbackQuery, callback_data: Px, bot: Bot, session: AsyncSession, user: User,
                         settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    link = await _link(cb, session, channel, callback_data.id) if channel else None
    if link is None:
        return
    if callback_data.a == "lnk_del":
        await cb.answer()
        await _edit(cb, t("lnk.revoke_confirm", name=html.escape(link.name)), markup([
            [btn(t("lnk.revoke_yes"), Px(a="lnk_delok", c=channel.id, id=link.id))],
            [btn(t("btn.back"), Px(a="lnk", c=channel.id, id=link.id))],
        ]))
        return
    try:
        await bot.revoke_chat_invite_link(channel.chat_id, link.url)
    except TelegramAPIError:
        pass
    link.revoked = True
    await session.flush()
    await cb.answer(t("lnk.revoked"))
    await _edit(cb, *await links_view(session, channel))


# ---- join requests and welcome ------------------------------------------------------------------

def join_view(channel: Channel) -> tuple[str, InlineKeyboardMarkup]:
    s = growth.join_settings(channel.join_settings)
    c = channel.id
    welcome = s["welcome_html"] or t("jr.welcome_default")
    lines = [
        t("jr.title", title=html.escape(channel.title)), "", t("jr.help"), "",
        t("jr.approve_line", value=_approve_label(s["approve"])),
        t("jr.welcome_on") if s["welcome"] else t("jr.welcome_off"),
    ]
    if s["welcome"]:
        lines += ["", t("jr.welcome_preview"), welcome]
    if s["link"]:
        lines += ["", t("jr.link_line", url=html.escape(s["link"]))]
    rows = [
        [btn(t("jr.approve_btn", value=_approve_label(s["approve"])), Px(a="jr_ap", c=c))],
        [btn(on(bool(s["welcome"])) + t("jr.welcome_btn"), Px(a="jr_wt", c=c)),
         btn(t("jr.welcome_text_btn"), Px(a="jr_wtext", c=c))],
    ]
    if not s["link"]:
        rows.append([btn(t("jr.link_btn"), Px(a="jr_link", c=c))])
    rows.append([btn(t("btn.back"), Pj(a="ch", c=c))])
    return "\n".join(lines), markup(rows)


@router.callback_query(Px.filter(F.a.in_({"join", "jr_ap", "jr_wt", "jr_link"})))
async def px_join(cb: CallbackQuery, callback_data: Px, bot: Bot, session: AsyncSession, state: FSMContext,
                  user: User, settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    if channel is None:
        return
    s = growth.join_settings(channel.join_settings)
    a = callback_data.a
    if a == "jr_ap":
        choices = growth.APPROVE_CHOICES
        s["approve"] = choices[(choices.index(s["approve"]) + 1) % len(choices)] if s["approve"] in choices else "now"
    elif a == "jr_wt":
        s["welcome"] = not s["welcome"]
    elif a == "jr_link":
        try:
            invite = await bot.create_chat_invite_link(channel.chat_id, name="FlowPost", creates_join_request=True)
        except TelegramAPIError:
            await cb.answer(t("lnk.err_create"), show_alert=True)
            return
        s["link"] = invite.invite_link
    if a != "join":
        channel.join_settings = s
        await session.flush()
    await state.set_state(None)
    await cb.answer()
    await _edit(cb, *join_view(channel))


@router.callback_query(Px.filter(F.a == "jr_wtext"))
async def px_welcome_ask(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                         settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    if channel is None:
        return
    await state.set_state(ProInput.welcome)
    await state.update_data(px_channel=channel.id)
    await cb.answer()
    await _edit(cb, t("jr.welcome_prompt", max=growth.MAX_WELCOME), markup([_back(channel, "join")]))


@router.message(ProInput.welcome, F.text)
async def in_welcome(message: Message, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel = await _input_channel(message, session, state, user)
    if channel is None:
        return
    text = message.html_text.strip()
    if not text or len(text) > growth.MAX_WELCOME:
        await message.answer(t("jr.welcome_prompt", max=growth.MAX_WELCOME))
        return
    channel.join_settings = {**growth.join_settings(channel.join_settings), "welcome_html": text, "welcome": True}
    await session.flush()
    await state.set_state(None)
    view, kb = join_view(channel)
    await message.answer(t("jr.welcome_saved") + "\n\n" + view, reply_markup=kb, disable_web_page_preview=True)


# ---- RSS sources --------------------------------------------------------------------------------

async def rss_view(session: AsyncSession, channel: Channel) -> tuple[str, InlineKeyboardMarkup]:
    feeds = (await session.scalars(select(Feed).where(Feed.channel_id == channel.id).order_by(Feed.id))).all()
    lines = [t("rss.title", title=html.escape(channel.title)), "", t("rss.help")]
    rows = [[btn(t("rss.add"), Px(a="rss_new", c=channel.id))]] if len(feeds) < MAX_FEEDS else []
    if feeds:
        lines.append("")
    for i, feed in enumerate(feeds, 1):
        state = "⏸ " if not feed.active else ("⚠️ " if feed.last_error else "")
        mode = t("rss.mode_auto") if feed.mode == "auto" else t("rss.mode_draft")
        lines.append(f"{i}. {state}<b>{html.escape(feed.title or feed.url)}</b> — {mode}")
        rows.append([btn(f"{i}. {snippet(feed.title or feed.url, 40)}", Px(a="feed", c=channel.id, id=feed.id))])
    rows.append(_back(channel))
    return "\n".join(lines), markup(rows)


def feed_view(channel: Channel, feed: Feed) -> tuple[str, InlineKeyboardMarkup]:
    c = channel.id
    lines = [
        t("rss.feed_title", title=html.escape(feed.title or feed.url)),
        html.escape(feed.url),
        "",
        t("rss.mode_line", mode=t("rss.mode_auto") if feed.mode == "auto" else t("rss.mode_draft")),
        t("rss.ai_on") if feed.rewrite else t("rss.ai_off"),
        t("rss.active") if feed.active else t("rss.paused"),
    ]
    if feed.last_error:
        lines.append("⚠️ " + t(feed.last_error))
    rows = [
        [btn(t("rss.mode_btn"), Px(a="feed_mode", c=c, id=feed.id)),
         btn(on(feed.rewrite) + t("rss.ai_btn"), Px(a="feed_ai", c=c, id=feed.id))],
        [btn(t("rss.pause_btn") if feed.active else t("rss.resume_btn"), Px(a="feed_on", c=c, id=feed.id)),
         btn(t("rss.delete_btn"), Px(a="feed_del", c=c, id=feed.id))],
        _back(channel, "rss"),
    ]
    return "\n".join(lines), markup(rows)


@router.callback_query(Px.filter(F.a == "rss"))
async def px_rss(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                 settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    await state.set_state(None)
    await cb.answer()
    await _edit(cb, *await rss_view(session, channel))


@router.callback_query(Px.filter(F.a.in_({"feed", "feed_mode", "feed_ai", "feed_on", "feed_del"})))
async def px_feed(cb: CallbackQuery, callback_data: Px, session: AsyncSession, user: User, settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings, paid=callback_data.a != "feed_del")
    feed = await session.get(Feed, callback_data.id) if channel else None
    if channel is None:
        return
    if feed is None or feed.channel_id != channel.id:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    a = callback_data.a
    if a == "feed_del":
        await session.delete(feed)
        await session.flush()
        await cb.answer(t("rss.deleted"))
        await _edit(cb, *await rss_view(session, channel))
        return
    if a == "feed_mode":
        feed.mode = "draft" if feed.mode == "auto" else "auto"
    elif a == "feed_ai":
        feed.rewrite = not feed.rewrite
    elif a == "feed_on":
        feed.active = not feed.active
        feed.last_error = None
    await session.flush()
    await cb.answer()
    await _edit(cb, *feed_view(channel, feed))


@router.callback_query(Px.filter(F.a == "rss_new"))
async def px_rss_ask(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                     settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    await state.set_state(ProInput.feed_url)
    await state.update_data(px_channel=channel.id)
    await cb.answer()
    await _edit(cb, t("rss.url_prompt"), markup([_back(channel, "rss")]))


@router.message(ProInput.feed_url, F.text)
async def in_feed_url(message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel = await _input_channel(message, session, state, user)
    if channel is None:
        return
    url = (message.text or "").strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    checking = await message.answer(t("rss.checking"))

    async def reply(text: str, kb: InlineKeyboardMarkup) -> None:
        await bot.edit_message_text(text, chat_id=message.chat.id, message_id=checking.message_id, reply_markup=kb,
                                    disable_web_page_preview=True)

    try:
        parsed = rss.parse(await rss.fetch(url))
    except rss.FeedError as e:
        await reply(t(e.key) + "\n\n" + t("rss.url_prompt"), markup([_back(channel, "rss")]))
        return
    # What the source already has is taken as seen: only items that appear from now on become posts.
    feed = Feed(channel_id=channel.id, url=url[:512], title=parsed.title or url[:256],
                seen=[i.id for i in parsed.items][:rss.MAX_SEEN], checked_at=utcnow())
    session.add(feed)
    await session.flush()
    await state.set_state(None)
    text, kb = feed_view(channel, feed)
    await reply(t("rss.added", n=len(parsed.items)) + "\n\n" + text, kb)


async def _draft(cb: CallbackQuery, session: AsyncSession, user: User, post_id: int) -> Post | None:
    post = await posts_repo.get_post(session, user.id, post_id)
    if post is None or post.status != "draft":
        await cb.answer(t("rss.draft_gone"), show_alert=True)
        if cb.message is not None:
            try:
                await cb.message.edit_reply_markup(reply_markup=None)
            except TelegramAPIError:
                pass
        return None
    return post


@router.callback_query(Px.filter(F.a == "rss_pub"))
async def px_rss_publish(cb: CallbackQuery, callback_data: Px, session: AsyncSession, user: User, worker: Worker) -> None:
    post = await _draft(cb, session, user, callback_data.id)
    if post is None:
        return
    await cb.answer(t("pub.working"))
    report, _ = await publish_now(session, worker, post)
    if cb.message is not None:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await cb.message.answer(report, disable_web_page_preview=True)


@router.callback_query(Px.filter(F.a == "rss_edit"))
async def px_rss_edit(cb: CallbackQuery, callback_data: Px, bot: Bot, session: AsyncSession, state: FSMContext,
                      user: User, publisher: Publisher) -> None:
    post = await _draft(cb, session, user, callback_data.id)
    if post is None:
        return
    await cb.answer()
    await open_editor(bot, cb.from_user.id, session, state, user, post, publisher)


@router.callback_query(Px.filter(F.a == "rss_skip"))
async def px_rss_skip(cb: CallbackQuery, callback_data: Px, session: AsyncSession, user: User) -> None:
    post = await _draft(cb, session, user, callback_data.id)
    if post is None:
        return
    await session.delete(post)
    await session.flush()
    await cb.answer(t("rss.skipped"))
    if cb.message is not None:
        try:
            await cb.message.delete()
        except TelegramAPIError:
            pass


# ---- AI content plan ----------------------------------------------------------------------------

def plan_view(channel: Channel, ideas: list[str]) -> tuple[str, InlineKeyboardMarkup]:
    lines = [t("plan.title", title=html.escape(channel.title)), ""]
    for i, idea in enumerate(ideas, 1):
        first = re.sub(r"<[^>]+>", "", idea.strip().splitlines()[0]) if idea.strip() else ""
        lines.append(f"{i}. {html.escape(snippet(first, 70))}")
    lines += ["", t("plan.help")]
    numbers = [btn(f"✍️ {i}", Px(a="plan_use", c=channel.id, v=str(i - 1))) for i in range(1, len(ideas) + 1)]
    rows = chunked(numbers, 4)
    rows += [[btn(t("plan.again"), Px(a="plan", c=channel.id))], _back(channel)]
    return "\n".join(lines), markup(rows)


@router.callback_query(Px.filter(F.a == "plan"))
async def px_plan(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                  settings: Settings, ai: AIService) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    if not ai.enabled:
        await cb.answer(t("ai.disabled"), show_alert=True)
        return
    await cb.answer()
    await _edit(cb, t("plan.working"), None)
    try:
        ideas = await ideas_service.generate(session, settings, ai, user, channel)
    except ideas_service.IdeasError as e:
        await _edit(cb, t(e.key), markup([_back(channel)]))
        return
    # Kept as idea posts, so the week's drafts also wait in the channel's calendar to be dragged onto a day.
    posts = await ideas_service.save(session, channel, ideas)
    await state.update_data(plan_channel=channel.id, plan_ideas=[p.id for p in posts])
    await _edit(cb, *plan_view(channel, ideas))


@router.callback_query(Px.filter(F.a == "plan_use"))
async def px_plan_use(cb: CallbackQuery, callback_data: Px, bot: Bot, session: AsyncSession, state: FSMContext,
                      user: User, settings: Settings, publisher: Publisher) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    data = await state.get_data()
    ideas = data.get("plan_ideas") or []
    idx = int(callback_data.v) if callback_data.v.isdigit() else -1
    post = None
    if data.get("plan_channel") == channel.id and 0 <= idx < len(ideas) and isinstance(ideas[idx], int):
        post = await posts_repo.get_post(session, user.id, ideas[idx])
    if post is None:
        await cb.answer(t("plan.expired"), show_alert=True)
        return
    await cb.answer()
    await open_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=t("plan.opened", n=idx + 1))


# ---- ideas: whatever the owner sent the bot and parked with «💡 В ідеї», plus the AI plan's drafts ----------------

IDEAS_SHOWN = 20


async def _poster_channel(
    cb: CallbackQuery, data: Px, session: AsyncSession, user: User, settings: Settings,
) -> Channel | None:
    """Like `_channel`, but anyone who may post to the channel may keep ideas for it."""
    channel = await channels_repo.get_channel(session, user.id, data.c)
    if channel is not None and channel.owner_id != user.id and not await channel_admins_repo.has_permission(
        session, channel.id, user.id, "posts"
    ):
        channel = None
    if channel is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return None
    if not await _extras(session, settings, channel):
        await cb.answer(t("paywall.extras_short"), show_alert=True)
        if cb.message is not None:
            await cb.message.answer(t("idea.paywall"), reply_markup=paywall_kb(settings))
        return None
    return channel


async def ideas_view(
    session: AsyncSession, user: User, channel: Channel, *, from_card: bool = False,
) -> tuple[str, InlineKeyboardMarkup]:
    """The channel's ideas. «Назад» leads to the PRO tools, or to the channel card for whoever came from there or
    may post but not see the PRO tools."""
    posts = (await ideas_service.for_channel(session, channel))[:IDEAS_SHOWN]
    lines = [t("idea.title", title=html.escape(channel.title)), "", t("idea.help")]
    lines += ["", t("idea.pick") if posts else t("idea.empty")]
    rows = []
    for i, post in enumerate(posts, 1):
        first = post.parts[0] if post.parts else None
        text = snippet(part_preview_text(first), 40) if first else ""
        icon = "🖼 " if first and first.media else ""
        rows.append([btn(f"{i}. {icon}{text or t('parts.no_text')}", Px(a="idea_open", c=channel.id, id=post.id))])
    can_settings = channel.owner_id == user.id or await channel_admins_repo.has_permission(
        session, channel.id, user.id, "settings"
    )
    to_menu = can_settings and not from_card
    rows.append([btn(t("btn.back"), Px(a="menu", c=channel.id) if to_menu else Pj(a="ch", c=channel.id))])
    return "\n".join(lines), markup(rows)


@router.callback_query(Px.filter(F.a == "ideas"))
async def px_ideas(cb: CallbackQuery, callback_data: Px, session: AsyncSession, user: User, settings: Settings) -> None:
    channel = await _poster_channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    await cb.answer()
    await _edit(cb, *await ideas_view(session, user, channel, from_card=callback_data.v == "ch"))


@router.callback_query(Px.filter(F.a == "idea_open"))
async def px_idea_open(cb: CallbackQuery, callback_data: Px, bot: Bot, session: AsyncSession, state: FSMContext,
                       user: User, settings: Settings, publisher: Publisher) -> None:
    channel = await _poster_channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    post = await posts_repo.get_post(session, user.id, callback_data.id)
    if post is None or not ideas_service.is_idea(post) or post.channel_ids != [channel.id]:
        await cb.answer(t("idea.gone"), show_alert=True)
        await _edit(cb, *await ideas_view(session, user, channel))
        return
    await cb.answer()
    await open_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=t("idea.opened"))


# ---- giveaways: free for every channel, opened from the channel card ------------------------------------------------------------
# Two kinds: among whoever commented on a post (needs the discussion group), and with a «Беру участь» button under
# a post the owner writes here — whoever taps it enters.

BUTTON_PRESETS = ("gwb.preset_0", "gwb.preset_1", "gwb.preset_2")


async def _giveaway_pub(cb: CallbackQuery, session: AsyncSession, channel: Channel, pub_id: int) -> Publication | None:
    pub = await session.get(Publication, pub_id)
    if pub is None or pub.channel_id != channel.id or pub.status != "published":
        await cb.answer(t("err.post_not_found"), show_alert=True)
        return None
    return pub


async def _button_giveaway(cb: CallbackQuery, session: AsyncSession, channel: Channel, gw_id: int) -> Giveaway | None:
    gw = await session.get(Giveaway, gw_id)
    if gw is None or gw.channel_id != channel.id or gw.post_id is None:
        await cb.answer(t("gwb.gone"), show_alert=True)
        return None
    return gw


async def _pub_title(session: AsyncSession, pub: Publication, limit: int) -> str:
    return await _post_title(await session.get(Post, pub.post_id), limit)


async def _post_title(post: Post | None, limit: int) -> str:
    text = snippet(part_preview_text(post.parts[0]), limit) if post and post.parts else ""
    return text or t("parts.no_text")


async def _giveaway_publication(session: AsyncSession, gw: Giveaway) -> Publication | None:
    """The giveaway post as it went out in the giveaway's channel."""
    pubs = await pubs_repo.published_for_post(session, gw.post_id) if gw.post_id else []
    return next((p for p in pubs if p.channel_id == gw.channel_id), None)


async def giveaway_view(session: AsyncSession, user: User, channel: Channel) -> tuple[str, InlineKeyboardMarkup]:
    lines = [t("gw.title", title=html.escape(channel.title)), "", t("gw.help")]
    c = channel.id
    zone = tz_of(user.tz)
    rows = [[btn(t("gwb.new"), Px(a="gb_new", c=c), style="success")]]
    giveaways = (await session.scalars(
        select(Giveaway)
        .where(Giveaway.channel_id == c, Giveaway.post_id.is_not(None))
        .order_by(Giveaway.id.desc())
        .limit(GIVEAWAY_POSTS)
    )).all()
    if giveaways:
        lines += ["", t("gwb.pick")]
    for gw in giveaways:
        post = await session.get(Post, gw.post_id)
        icon = "🔒" if not gw.is_open else ("✅" if post is not None and post.status == "published" else "📝")
        when = gw.created_at.astimezone(zone).strftime("%d.%m")
        label = f"{icon} {when} · {await _post_title(post, 24)} · 👥 {gw.entries}"
        rows.append([btn(label, Px(a="gb", c=c, id=gw.id))])
    back = [btn(t("btn.back"), Pj(a="ch", c=c))]
    if not channel.discussion_chat_id:
        lines += ["", t("gw.no_group")]
        return "\n".join(lines), markup([*rows, [btn(t("proj.comments_btn"), Cs(a="cm", c=c))], back])
    pubs = (await session.scalars(
        select(Publication)
        .where(Publication.channel_id == c, Publication.status == "published",
               Publication.deleted.is_(False))
        .order_by(Publication.published_at.desc(), Publication.id.desc())
        .limit(GIVEAWAY_POSTS)
    )).all()
    counts = dict((await session.execute(
        select(Commenter.publication_id, func.count(Commenter.id))
        .where(Commenter.publication_id.in_([p.id for p in pubs]))
        .group_by(Commenter.publication_id)
    )).all()) if pubs else {}
    lines += ["", t("gw.pick_post") if pubs else t("gw.no_posts")]
    for pub in pubs:
        when = (pub.published_at or pub.run_at).astimezone(zone).strftime("%d.%m")
        label = f"💬 {when} · {await _pub_title(session, pub, 24)} · 👥 {counts.get(pub.id, 0)}"
        rows.append([btn(label, Px(a="gw_post", c=c, id=pub.id, v="s"))])
    rows.append(back)
    return "\n".join(lines), markup(rows)


def _count_rows(c: int, run: str, ask: str, id_: int, mode: str) -> list[list]:
    return [
        [btn(t(f"gw.run_{n}"), Px(a=run, c=c, id=id_, v=f"{n}{mode}"), style="success") for n in giveaway.WINNER_CHOICES],
        [btn(t("gw.run_custom"), Px(a=ask, c=c, id=id_, v=mode))],
    ]


async def giveaway_post_view(
    session: AsyncSession, channel: Channel, pub: Publication, subscribers_only: bool,
) -> tuple[str, InlineKeyboardMarkup]:
    total = len(await giveaway.entrants(session, pub.id))
    lines = [
        t("gw.post_title"), "",
        f"<i>{html.escape(await _pub_title(session, pub, 120))}</i>", "",
        t("gw.entrants", n=total),
        t("gw.subs_on") if subscribers_only else t("gw.subs_off"),
    ]
    c, mode = channel.id, "s" if subscribers_only else "a"
    rows = []
    if total:
        lines += ["", t("gw.choose_count")]
        rows += _count_rows(c, "gw_run", "gw_ask", pub.id, mode)
    else:
        lines += ["", t("gw.no_entrants")]
    rows += [
        [btn(on(subscribers_only) + t("gw.subs_btn"), Px(a="gw_post", c=c, id=pub.id, v="a" if subscribers_only else "s"))],
        [btn(t("btn.back"), Px(a="gw", c=c))],
    ]
    return "\n".join(lines), markup(rows)


async def button_giveaway_view(session: AsyncSession, channel: Channel, gw: Giveaway) -> tuple[str, InlineKeyboardMarkup]:
    post = await session.get(Post, gw.post_id) if gw.post_id else None
    published = post is not None and post.status == "published"
    status = "gwb.st_published" if published else ("gwb.st_scheduled" if post and post.status == "scheduled" else "gwb.st_draft")
    lines = [
        t("gwb.title"), "",
        f"<i>{html.escape(await _post_title(post, 120))}</i>", "",
        t(status),
        t("gwb.button", text=html.escape(gw.button_text)),
        t("gwb.entrants", n=gw.entries),
        t("gwb.open") if gw.is_open else t("gwb.closed"),
        t("gwb.subs_on") if gw.subscribers_only else t("gwb.subs_off"),
    ]
    c, mode = channel.id, "s" if gw.subscribers_only else "a"
    rows = []
    if gw.entries:
        lines += ["", t("gw.choose_count")]
        rows += _count_rows(c, "gb_run", "gb_ask", gw.id, mode)
    elif not published:
        lines += ["", t("gwb.not_published")]
    else:
        lines += ["", t("gwb.no_entrants")]
    if not published and post is not None:
        rows.append([btn(t("gwb.open_post"), Px(a="gb_post", c=c, id=gw.id))])
    rows += [
        [btn(on(gw.subscribers_only) + t("gw.subs_btn"), Px(a="gb_subs", c=c, id=gw.id))],
        [btn(t("gwb.close_btn") if gw.is_open else t("gwb.reopen_btn"), Px(a="gb_open", c=c, id=gw.id))],
        [btn(t("btn.back"), Px(a="gw", c=c))],
    ]
    return "\n".join(lines), markup(rows)


@router.callback_query(Px.filter(F.a == "gw"))
async def px_giveaway(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                      settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    if channel is None:
        return
    await state.set_state(None)
    await cb.answer()
    await _edit(cb, *await giveaway_view(session, user, channel))


@router.callback_query(Px.filter(F.a == "gw_post"))
async def px_giveaway_post(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                           settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    pub = await _giveaway_pub(cb, session, channel, callback_data.id) if channel else None
    if pub is None:
        return
    await state.set_state(None)
    await cb.answer()
    await _edit(cb, *await giveaway_post_view(session, channel, pub, callback_data.v != "a"))


# ---- a giveaway with a «Беру участь» button ----------------------------------------------------

@router.callback_query(Px.filter(F.a == "gb_new"))
async def px_button_giveaway_new(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext,
                                 user: User, settings: Settings) -> None:
    """Step 1: what the button says — a preset or typed in."""
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    if channel is None:
        return
    await state.set_state(ProInput.gw_button)
    await state.update_data(px_channel=channel.id)
    await cb.answer()
    c = channel.id
    rows = [[btn(t(key), Px(a="gb_mk", c=c, v=str(i)))] for i, key in enumerate(BUTTON_PRESETS)]
    rows.append([btn(t("btn.back"), Px(a="gw", c=c))])
    await _edit(cb, t("gwb.button_prompt", max=giveaway.MAX_BUTTON_TEXT), markup(rows))


async def _start_button_giveaway(
    bot: Bot, chat_id: int, session: AsyncSession, state: FSMContext, user: User, settings: Settings,
    publisher: Publisher, channel: Channel, button_text: str,
) -> None:
    """Step 2: the giveaway post as a draft with the button under it, in the editor — the owner writes the text,
    adds a photo, then publishes or schedules it like any post."""
    gw = await giveaway.create(session, channel, button_text)
    post = await posts_repo.create_post(
        session, channel.owner_id, [channel.id], options={**initial_options(channel, False), "link_preview": False},
        text=t("gwb.template", title=html.escape(channel.title), button=html.escape(gw.button_text)),
        buttons=[[giveaway.entry_button(gw)]],
    )
    gw.post_id = post.id
    await session.flush()
    await state.set_state(None)
    await open_editor(bot, chat_id, session, state, user, post, publisher, note=t("gwb.opened"))


@router.callback_query(Px.filter(F.a == "gb_mk"))
async def px_button_giveaway_preset(cb: CallbackQuery, callback_data: Px, bot: Bot, session: AsyncSession,
                                    state: FSMContext, user: User, settings: Settings, publisher: Publisher) -> None:
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    if channel is None:
        return
    idx = int(callback_data.v) if callback_data.v.isdigit() and int(callback_data.v) < len(BUTTON_PRESETS) else 0
    await cb.answer()
    await _drop_buttons(cb)
    await _start_button_giveaway(bot, cb.from_user.id, session, state, user, settings, publisher, channel,
                                 t(BUTTON_PRESETS[idx]))


@router.message(ProInput.gw_button, F.text)
async def in_giveaway_button(message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
                             settings: Settings, publisher: Publisher) -> None:
    channel = await _input_channel(message, session, state, user)
    if channel is None:
        return
    text = (message.text or "").strip()
    if not text or text.startswith("/") or len(text) > giveaway.MAX_BUTTON_TEXT:
        await message.answer(t("gwb.button_prompt", max=giveaway.MAX_BUTTON_TEXT))
        return
    await _start_button_giveaway(bot, message.chat.id, session, state, user, settings, publisher, channel, text)


@router.callback_query(Px.filter(F.a.in_({"gb", "gb_subs", "gb_open"})))
async def px_button_giveaway(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext,
                             user: User, settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    gw = await _button_giveaway(cb, session, channel, callback_data.id) if channel else None
    if gw is None:
        return
    if callback_data.a == "gb_subs":
        gw.subscribers_only = not gw.subscribers_only
    elif callback_data.a == "gb_open":
        gw.is_open = not gw.is_open
    await session.flush()
    await state.set_state(None)
    await cb.answer()
    await _edit(cb, *await button_giveaway_view(session, channel, gw))


@router.callback_query(Px.filter(F.a == "gb_post"))
async def px_button_giveaway_post(cb: CallbackQuery, callback_data: Px, bot: Bot, session: AsyncSession,
                                  state: FSMContext, user: User, settings: Settings, publisher: Publisher) -> None:
    """The giveaway post, not published yet, back in the editor."""
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    gw = await _button_giveaway(cb, session, channel, callback_data.id) if channel else None
    post = await session.get(Post, gw.post_id) if gw else None
    if post is None:
        return
    if post.status == "published":
        await cb.answer(t("gwb.already_published"), show_alert=True)
        return
    await cb.answer()
    await open_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=t("gwb.opened"))


# ---- drawing the winners (both kinds) ----------------------------------------------------------

@router.callback_query(Px.filter(F.a.in_({"gw_ask", "gb_ask"})))
async def px_giveaway_ask(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                          settings: Settings) -> None:
    """«✍️ Своя кількість»: the number of winners is typed in."""
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    if channel is None:
        return
    mode = "a" if callback_data.v == "a" else "s"
    if callback_data.a == "gb_ask":
        gw = await _button_giveaway(cb, session, channel, callback_data.id)
        if gw is None:
            return
        await state.update_data(gw_pub=None, gw_btn=gw.id)
        back = Px(a="gb", c=channel.id, id=gw.id)
    else:
        pub = await _giveaway_pub(cb, session, channel, callback_data.id)
        if pub is None:
            return
        await state.update_data(gw_pub=pub.id, gw_btn=None)
        back = Px(a="gw_post", c=channel.id, id=pub.id, v=mode)
    await state.set_state(ProInput.gw_count)
    await state.update_data(px_channel=channel.id, gw_mode=mode)
    await cb.answer()
    await _edit(cb, t("gw.count_prompt", max=giveaway.MAX_WINNERS), markup([[btn(t("btn.back"), back)]]))


async def _draw_view(
    bot: Bot, session: AsyncSession, state: FSMContext, user: User, channel: Channel,
    pool: list, post_pub: Publication | None, count: int, mode: str, back: Px, reroll: Px, close: int | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Draw `count` winners among `pool` and show the announcement with what can be done with it. `close` is the
    button giveaway that stops taking entries once the announcement is used."""
    owner = await session.get(User, channel.owner_id)
    winners = await giveaway.draw(bot, channel, pool, count, subscribers_only=mode == "s",
                                  exclude={owner.tg_id} if owner else set())
    if not winners:
        return t("gw.none_eligible"), markup([[btn(t("btn.back"), back)]])
    ids = publication_message_ids(post_pub) if post_pub is not None else []
    result = giveaway.result_html(winners, len(pool), message_link(channel, ids[0]) if ids else None, utcnow(), user.tz)
    await state.update_data(gw_channel=channel.id, gw_text=result, gw_close=close)
    lines = [t("gw.drawn_note")]
    if len(winners) < count:
        lines.append(t("gw.fewer", n=len(winners)))
    lines += ["", "➖➖➖➖➖➖➖➖", "", result]
    c, p = channel.id, reroll.id
    rows = [
        [btn(t("gw.publish_now"), Px(a="gw_pub", c=c, id=p), style="success")],
        [btn(t("gw.schedule"), Px(a="gw_sched", c=c, id=p)), btn(t("gw.edit"), Px(a="gw_edit", c=c, id=p))],
        [btn(t("gw.reroll"), reroll)],
        [btn(t("btn.back"), back)],
    ]
    return "\n".join(lines), markup(rows)


async def _comment_draw(bot: Bot, session: AsyncSession, state: FSMContext, user: User, channel: Channel,
                        pub: Publication, count: int, mode: str) -> tuple[str, InlineKeyboardMarkup]:
    return await _draw_view(
        bot, session, state, user, channel, await giveaway.entrants(session, pub.id), pub, count, mode,
        Px(a="gw_post", c=channel.id, id=pub.id, v=mode), Px(a="gw_run", c=channel.id, id=pub.id, v=f"{count}{mode}"),
    )


async def _button_draw(bot: Bot, session: AsyncSession, state: FSMContext, user: User, channel: Channel,
                       gw: Giveaway, count: int, mode: str) -> tuple[str, InlineKeyboardMarkup]:
    return await _draw_view(
        bot, session, state, user, channel, await giveaway.button_entrants(session, gw.id),
        await _giveaway_publication(session, gw), count, mode,
        Px(a="gb", c=channel.id, id=gw.id), Px(a="gb_run", c=channel.id, id=gw.id, v=f"{count}{mode}"), close=gw.id,
    )


def _run_args(v: str) -> tuple[int, str]:
    digits, mode = v[:-1], "a" if v.endswith("a") else "s"
    return (min(max(int(digits), 1), giveaway.MAX_WINNERS) if digits.isdigit() else 1), mode


@router.callback_query(Px.filter(F.a == "gw_run"))
async def px_giveaway_run(cb: CallbackQuery, callback_data: Px, bot: Bot, session: AsyncSession, state: FSMContext,
                          user: User, settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    pub = await _giveaway_pub(cb, session, channel, callback_data.id) if channel else None
    if pub is None:
        return
    count, mode = _run_args(callback_data.v)
    await cb.answer(t("gw.drawing"))
    await _edit(cb, *await _comment_draw(bot, session, state, user, channel, pub, count, mode))


@router.callback_query(Px.filter(F.a == "gb_run"))
async def px_button_giveaway_run(cb: CallbackQuery, callback_data: Px, bot: Bot, session: AsyncSession,
                                 state: FSMContext, user: User, settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    gw = await _button_giveaway(cb, session, channel, callback_data.id) if channel else None
    if gw is None:
        return
    count, mode = _run_args(callback_data.v)
    await cb.answer(t("gw.drawing"))
    await _edit(cb, *await _button_draw(bot, session, state, user, channel, gw, count, mode))


@router.message(ProInput.gw_count, F.text)
async def in_giveaway_count(message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel = await _input_channel(message, session, state, user)
    if channel is None:
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or not 1 <= int(raw) <= giveaway.MAX_WINNERS:
        await message.answer(t("gw.count_prompt", max=giveaway.MAX_WINNERS))
        return
    data = await state.get_data()
    mode = data.get("gw_mode") or "s"
    await state.set_state(None)
    if data.get("gw_btn"):
        gw = await session.get(Giveaway, int(data["gw_btn"]))
        if gw is None or gw.channel_id != channel.id or gw.post_id is None:
            await message.answer(t("gwb.gone"))
            return
        text, kb = await _button_draw(bot, session, state, user, channel, gw, int(raw), mode)
    else:
        pub = await session.get(Publication, int(data.get("gw_pub") or 0))
        if pub is None or pub.channel_id != channel.id or pub.status != "published":
            await message.answer(t("err.post_not_found"))
            return
        text, kb = await _comment_draw(bot, session, state, user, channel, pub, int(raw), mode)
    await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


async def _giveaway_post(cb: CallbackQuery, session: AsyncSession, state: FSMContext, channel: Channel) -> Post | None:
    """The drawn result as a new draft post for the channel — once: a second tap finds nothing left to use.
    A button giveaway stops taking entries now that its winners are out."""
    data = await state.get_data()
    text = data.get("gw_text")
    if not text or data.get("gw_channel") != channel.id:
        await cb.answer(t("gw.expired"), show_alert=True)
        return None
    await state.update_data(gw_text=None, gw_close=None)
    gw = await session.get(Giveaway, int(data["gw_close"])) if data.get("gw_close") else None
    if gw is not None and gw.channel_id == channel.id:
        gw.is_open = False
    return await posts_repo.create_post(
        session, channel.owner_id, [channel.id], options={**initial_options(channel, False), "link_preview": False},
        text=text,
    )


async def _drop_buttons(cb: CallbackQuery) -> None:
    if cb.message is not None:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass


@router.callback_query(Px.filter(F.a == "gw_pub"), flags={"publish": True})
async def px_giveaway_publish(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext,
                              user: User, settings: Settings, worker: Worker) -> None:
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    post = await _giveaway_post(cb, session, state, channel) if channel else None
    if post is None:
        return
    await cb.answer(t("pub.working"))
    report, _ = await publish_now(session, worker, post)
    await _drop_buttons(cb)
    if cb.message is not None:
        await cb.message.answer(report, disable_web_page_preview=True)


@router.callback_query(Px.filter(F.a.in_({"gw_sched", "gw_edit"})))
async def px_giveaway_editor(cb: CallbackQuery, callback_data: Px, bot: Bot, session: AsyncSession, state: FSMContext,
                             user: User, settings: Settings, publisher: Publisher) -> None:
    channel = await _channel(cb, callback_data, session, user, settings, paid=False)
    post = await _giveaway_post(cb, session, state, channel) if channel else None
    if post is None:
        return
    await cb.answer()
    await _drop_buttons(cb)
    await open_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=t("gw.opened"))
    if callback_data.a == "gw_sched":
        await show_schedule(bot, cb.from_user.id, session, state, user, post)


# ---- translation for multiposting ---------------------------------------------------------------

@router.callback_query(Px.filter(F.a.in_({"tr", "tr_set"})))
async def px_translate(cb: CallbackQuery, callback_data: Px, session: AsyncSession, user: User, settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings, paid=callback_data.v == "off")
    if channel is None:
        return
    if callback_data.a == "tr_set":
        channel.translate_lang = callback_data.v if callback_data.v in LANG_NAMES else None
        await session.flush()
    await cb.answer()
    current = channel.translate_lang
    c = channel.id
    options = [btn(on(current == code) + f"{LANG_FLAGS[code]} {LANG_NAMES[code]}", Px(a="tr_set", c=c, v=code))
               for code in LANG_NAMES]
    rows = [[btn(on(current is None) + t("pro.translate_off"), Px(a="tr_set", c=c, v="off"))], *chunked(options, 2), _back(channel)]
    await _edit(cb, t("tr.title", title=html.escape(channel.title)) + "\n\n" + t("tr.help"), markup(rows))


@router.message(ProInput.link_name)
@router.message(ProInput.link_cost)
@router.message(ProInput.welcome)
@router.message(ProInput.feed_url)
@router.message(ProInput.gw_count)
@router.message(ProInput.gw_button)
async def in_wrong(message: Message) -> None:
    await message.answer(t("err.expected_input"))
