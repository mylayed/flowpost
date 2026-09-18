"""«⭐ PRO-інструменти» of a channel: tracked ad links, join requests, RSS sources, the AI content plan,
translation for multiposting and the weekly report. They work while the channel is on a paid plan or trial."""
from __future__ import annotations

import html
import re
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Pj, Px
from flowpost.bot.handlers.editor.publish import publish_now
from flowpost.bot.handlers.editor.view import open_editor
from flowpost.bot.keyboards.common import btn, chunked, markup, on, paywall_kb
from flowpost.bot.states import ProInput
from flowpost.config import Settings
from flowpost.db.models import Channel, Feed, InviteLink, Post, User
from flowpost.db.repo import channel_admins as channel_admins_repo
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.db.repo import publications as pubs_repo
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services import analytics, growth, rss
from flowpost.services.ai import LANG_NAMES, AIError, AIService
from flowpost.services.billing import entitlements, limits
from flowpost.services.delivery import engagement_score
from flowpost.services.html_sanitize import snippet
from flowpost.services.posts import channel_defaults, initial_options, part_preview_text
from flowpost.services.publisher import Publisher
from flowpost.services.worker import Worker

router = Router(name="pro")

MAX_FEEDS = 10
PLAN_SIZE = 7
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
    lines = [t("pro.title", title=html.escape(channel.title)), "", t("pro.help")]
    if not await _extras(session, settings, channel):
        lines += ["", t("pro.locked")]
    lang = channel.translate_lang
    rows = [
        [btn(t("pro.links") + (f" ({links})" if links else ""), Px(a="links", c=c))],
        [btn(on(growth.handles_requests(channel)) + t("pro.join"), Px(a="join", c=c))],
        [btn(t("pro.rss") + (f" ({feeds})" if feeds else ""), Px(a="rss", c=c))],
        [btn(t("pro.plan"), Px(a="plan", c=c))],
        [btn(t("pro.translate", lang=(LANG_FLAGS.get(lang, "") + " " + LANG_NAMES[lang]) if lang in LANG_NAMES
               else t("pro.translate_off")), Px(a="tr", c=c))],
        [btn(on(channel.weekly_report) + t("pro.report"), Px(a="rep_t", c=c))],
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
    rows.append(_back(channel))
    return "\n".join(lines), markup(rows)


@router.callback_query(Px.filter(F.a.in_({"join", "jr_ap", "jr_wt", "jr_link"})))
async def px_join(cb: CallbackQuery, callback_data: Px, bot: Bot, session: AsyncSession, state: FSMContext,
                  user: User, settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
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
    channel = await _channel(cb, callback_data, session, user, settings)
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

async def _examples(session: AsyncSession, user: User, channel: Channel) -> list[str]:
    """Texts of the channel's most engaging posts of the last 30 days, for the AI to take after."""
    now = utcnow()
    pubs = await pubs_repo.published_between(session, user.id, now - timedelta(days=30), now, channel_ids=[channel.id])
    texts: list[str] = []
    for pub in sorted(pubs, key=engagement_score, reverse=True):
        post = await session.get(Post, pub.post_id)
        text = part_preview_text(post.parts[0]).strip() if post and post.parts else ""
        if text and text not in texts:
            texts.append(text[:700])
        if len(texts) >= 8:
            break
    return texts


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
    used = await analytics.count_since(session, user.id, "ai_call", utcnow() - timedelta(days=1))
    if used >= settings.ai_daily_limit_paid:
        await cb.answer(t("ai.quota_over"), show_alert=True)
        return
    if not await limits.take(session, channel.id, "ai_text"):
        await cb.answer(t("ai.quota_channel_over"), show_alert=True)
        return
    await session.commit()  # the AI text is spent before the long request, so two taps can't both use the last one
    await cb.answer()
    await _edit(cb, t("plan.working"), None)
    try:
        ideas = await ai.content_plan(
            channel_title=channel.title, style=channel.ai_style_prompt,
            examples=await _examples(session, user, channel), lang=user.lang, count=PLAN_SIZE,
        )
    except AIError as e:
        await limits.add(session, channel.id, "ai_text", 1)
        await _edit(cb, t(e.key), markup([_back(channel)]))
        return
    analytics.track(session, user.id, "ai_call", action="plan")
    await state.update_data(plan_channel=channel.id, plan_ideas=ideas)
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
    if data.get("plan_channel") != channel.id or not 0 <= idx < len(ideas):
        await cb.answer(t("plan.expired"), show_alert=True)
        return
    await cb.answer()
    post = await posts_repo.create_post(
        session, channel.owner_id, [channel.id], options=initial_options(channel, False), text=ideas[idx],
        buttons=channel_defaults(channel)["buttons"],
    )
    await open_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=t("plan.opened", n=idx + 1))


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
async def in_wrong(message: Message) -> None:
    await message.answer(t("err.expected_input"))
