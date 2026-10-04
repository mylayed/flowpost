"""JSON API behind the billing Mini App; every /api request is authenticated with Telegram initData."""
from __future__ import annotations

import hashlib
import logging
import math
import time
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
from typing import Awaitable, Callable

from aiogram.exceptions import TelegramAPIError
from aiogram.types import User as TgUser
from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.config import Settings
from flowpost.db.models import Channel, Post, Publication, User
from flowpost.db.repo import channel_admins as channel_admins_repo
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.db.repo import publications as pubs_repo
from flowpost.db.repo import users as users_repo
from flowpost.db.types import utcnow
from flowpost.i18n import LANGS, t
from flowpost.services import ideas as ideas_service
from flowpost.services.billing import channel_subs, entitlements, limits, plans
from flowpost.services.billing.stars import create_topup_link
from flowpost.services.delivery import publication_message_ids
from flowpost.services.html_sanitize import html_to_plain, snippet
from flowpost.services.posts import message_link, part_icon, part_preview_text
from flowpost.services.slots import day_bounds_utc, local_now, to_utc, tz_of
from flowpost.webapp import AI_KEY, BOT_KEY, SESSIONMAKER_KEY, SETTINGS_KEY
from flowpost.webapp.auth import validate_init_data

log = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"
AUTH_SCHEME = "tma "

ApiHandler = Callable[[web.Request, AsyncSession, User], Awaitable[web.StreamResponse]]


def authed(fn: ApiHandler) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
    async def wrapper(request: web.Request) -> web.StreamResponse:
        settings = request.app[SETTINGS_KEY]
        header = request.headers.get("Authorization", "")
        tg = (
            validate_init_data(header[len(AUTH_SCHEME):], settings.bot_token.get_secret_value())
            if header.startswith(AUTH_SCHEME)
            else None
        )
        if tg is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        tg_user = TgUser(
            id=tg["id"], is_bot=False, first_name=tg.get("first_name") or "",
            username=tg.get("username"), language_code=tg.get("language_code"),
        )
        async with request.app[SESSIONMAKER_KEY]() as session:
            user, _ = await users_repo.get_or_create(session, tg_user, settings)
            response = await fn(request, session, user)
            await session.commit()
            return response

    return wrapper


async def _json_body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def days_left(until: datetime | None, now: datetime) -> int:
    return math.ceil((until - now).total_seconds() / 86400) if until and until > now else 0


async def channel_info(session: AsyncSession, settings: Settings, channel: Channel, owner: User, now: datetime) -> dict:
    """The channel's current plan, its validity, and the posts and quotas it has left, as shown in the Mini App."""
    entitlement = await entitlements.for_channel(session, settings, channel, owner, now)
    left = await entitlements.posts_left(session, settings, channel, owner, entitlement, now)
    return {
        "status": {"paid": "active", "trial": "active", "free": "free"}.get(entitlement.plan, "inactive"),
        "plan": entitlement.plan,
        "posts_per_day": entitlement.posts_per_day,
        "until": entitlement.until.isoformat() if entitlement.until else None,
        "days_left": days_left(entitlement.until, now),
        "posts_limit": entitlement.posts_limit,
        "posts_window": entitlement.window,
        "posts_left": left,
        "quotas": await limits.remaining(session, channel.id),
        "extras": entitlements.has_extras(entitlement),
    }


async def me(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    settings = request.app[SETTINGS_KEY]
    bot_user = await request.app[BOT_KEY].me()
    channels = await channels_repo.list_channels(session, user.id)
    now = utcnow()
    infos = [await channel_info(session, settings, c, user, now) for c in channels]
    return web.json_response({
        "user": {"first_name": user.first_name, "lang": user.lang, "tz": user.tz},
        "bot_username": bot_user.username,
        "balance": user.balance,
        "cashback": user.cashback,
        "cashback_percent": settings.cashback_percent,
        "usd_rate": settings.stars_usd_rate,
        "topup": {"min": settings.stars_topup_min, "max": settings.stars_topup_max},
        "legal": {"terms_url": settings.terms_url, "privacy_url": settings.privacy_url},
        "limit_prices": limits.public_prices(settings.limit_prices),
        "plans": plans.catalog(settings),
        "renew_soon_days": settings.renew_soon_days,
        "channels": [
            {"id": c.id, "title": c.title, "username": c.username, "kind": c.kind, **info}
            for c, info in zip(channels, infos)
        ],
    })


_bot_avatar_cache: bytes | None = None


async def bot_avatar(request: web.Request) -> web.Response:
    """The bot's own profile photo, proxied so the frontend never needs the bot token."""
    global _bot_avatar_cache
    if _bot_avatar_cache is None:
        bot = request.app[BOT_KEY]
        bot_user = await bot.me()
        photos = await bot.get_user_profile_photos(bot_user.id, limit=1)
        if not photos.photos:
            _bot_avatar_cache = b""
        else:
            file = await bot.get_file(photos.photos[0][-1].file_id)
            buf = await bot.download_file(file.file_path)
            _bot_avatar_cache = buf.read()
    if not _bot_avatar_cache:
        return web.Response(status=404)
    return web.Response(
        body=_bot_avatar_cache, content_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


async def owned_channel(session: AsyncSession, user: User, channel_id: int) -> Channel | None:
    channel = await session.get(Channel, channel_id)
    if channel is None or channel.owner_id != user.id or not channel.is_active:
        return None
    return channel


_chat_links: dict[int, tuple[float, str | None]] = {}
CHAT_LINK_TTL = 600  # seconds


async def open_link(bot, session: AsyncSession, channel: Channel) -> str:
    """A link that opens the channel itself in Telegram. A private channel's t.me/c/<id> without a message id only
    opens Telegram's website, so it uses the channel's invite link or, failing that, a message link: its latest
    published post, or message 1 (the "channel created" notice every channel starts with)."""
    if channel.username:
        return f"https://t.me/{channel.username}"
    cached = _chat_links.get(channel.chat_id)
    if cached is None or time.monotonic() - cached[0] > CHAT_LINK_TTL:
        try:
            chat = await bot.get_chat(channel.chat_id)
            link = f"https://t.me/{chat.username}" if chat.username else chat.invite_link
        except TelegramAPIError as e:
            log.info("get_chat for channel %s failed: %s", channel.id, e)
            link = None
        cached = (time.monotonic(), link)
        _chat_links[channel.chat_id] = cached
    if cached[1]:
        return cached[1]
    last = await session.scalar(
        select(Publication)
        .where(Publication.channel_id == channel.id, Publication.status == "published", Publication.deleted.is_(False))
        .order_by(Publication.published_at.desc())
        .limit(1)
    )
    ids = publication_message_ids(last) if last is not None else []
    return message_link(channel, ids[0] if ids else 1)


async def channel_detail(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    channel = await owned_channel(session, user, int(request.match_info["channel_id"]))
    if channel is None:
        return web.json_response({"error": "not_found"}, status=404)
    return web.json_response({
        "id": channel.id,
        "title": channel.title,
        "username": channel.username,
        "link": await open_link(request.app[BOT_KEY], session, channel),
        **await channel_info(session, request.app[SETTINGS_KEY], channel, user, utcnow()),
    })


async def transfer_options(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    now = utcnow()
    channels = await channels_repo.list_channels(session, user.id)
    subs = await channel_subs.by_channel(session, [c.id for c in channels])
    sources, targets = [], []
    for channel in channels:
        sub = subs.get(channel.id)
        if sub is None or sub.paid_until <= now:
            targets.append({"id": channel.id, "title": channel.title})
            continue
        sources.append({
            "id": channel.id,
            "title": channel.title,
            "posts_per_day": sub.posts_per_day,
            "until": sub.paid_until.isoformat(),
            "days_left": days_left(sub.paid_until, now),
            "quotas": await limits.remaining(session, channel.id),
        })
    return web.json_response({"sources": sources, "targets": targets})


async def transfer_subscription(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    body = await _json_body(request)
    from_id, to_id = body.get("from_id"), body.get("to_id")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (from_id, to_id)):
        return web.json_response({"error": "invalid_channels"}, status=400)
    if from_id == to_id:
        return web.json_response({"error": "same_channel"}, status=400)
    source = await owned_channel(session, user, from_id)
    target = await owned_channel(session, user, to_id)
    if source is None or target is None:
        return web.json_response({"error": "not_found"}, status=404)
    error = await channel_subs.transfer(session, source.id, target.id, user.id)
    if error:
        return web.json_response({"error": error}, status=409)
    return web.json_response({"ok": True})


async def limits_remaining(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    channel = await owned_channel(session, user, int(request.match_info["channel_id"]))
    if channel is None:
        return web.json_response({"error": "not_found"}, status=404)
    return web.json_response({"remaining": await limits.remaining(session, channel.id)})


async def buy_limits(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    settings = request.app[SETTINGS_KEY]
    body = await _json_body(request)
    channel_id, packs = body.get("channel_id"), body.get("packs")
    if not isinstance(channel_id, int) or isinstance(channel_id, bool) or not isinstance(packs, dict):
        return web.json_response({"error": "invalid_packs"}, status=400)
    channel = await owned_channel(session, user, channel_id)
    if channel is None:
        return web.json_response({"error": "not_found"}, status=404)
    total = limits.pack_total(settings.limit_prices, packs)
    if not total:
        return web.json_response({"error": "invalid_packs"}, status=400)
    if not await limits.buy_packs(session, user.id, channel.id, packs, total):
        missing = total - user.balance - user.cashback
        return web.json_response({"error": "insufficient_balance", "missing": missing}, status=402)
    return web.json_response({
        "balance": user.balance,
        "cashback": user.cashback,
        "remaining": await limits.remaining(session, channel.id),
    })


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


async def subscribe_channels(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    settings = request.app[SETTINGS_KEY]
    body = await _json_body(request)
    channel_ids, posts, days, stars = (body.get(k) for k in ("channel_ids", "posts_per_day", "days", "stars"))
    if (
        not isinstance(channel_ids, list)
        or not channel_ids
        or not all(_is_int(i) for i in channel_ids)
        or len(set(channel_ids)) != len(channel_ids)
        or not all(_is_int(v) for v in (posts, days, stars))
    ):
        return web.json_response({"error": "invalid_request"}, status=400)
    for channel_id in channel_ids:
        if await owned_channel(session, user, channel_id) is None:
            return web.json_response({"error": "not_found"}, status=404)
    quote = plans.quote(settings, posts, days, len(channel_ids), round_to_pack=body.get("round_to_pack") is True)
    if quote is None:
        return web.json_response({"error": "invalid_plan"}, status=400)
    total, term_days = quote
    if total != stars:
        return web.json_response({"error": "price_changed", "stars": total}, status=409)
    if not await channel_subs.buy(session, settings, user.id, channel_ids, posts, term_days, total):
        missing = total - user.balance - user.cashback
        return web.json_response({"error": "insufficient_balance", "missing": missing}, status=402)
    return web.json_response({"balance": user.balance, "cashback": user.cashback, "days": term_days})


async def topup(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    settings = request.app[SETTINGS_KEY]
    stars = (await _json_body(request)).get("stars")
    if (
        not isinstance(stars, int)
        or isinstance(stars, bool)
        or not settings.stars_topup_min <= stars <= settings.stars_topup_max
    ):
        return web.json_response({"error": "invalid_amount"}, status=400)
    try:
        link = await create_topup_link(request.app[BOT_KEY], user.id, stars, user.lang)
    except TelegramAPIError as e:
        log.warning("create_invoice_link failed: %s", e)
        return web.json_response({"error": "invoice_failed"}, status=502)
    return web.json_response({"link": link})


async def set_lang(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    lang = (await _json_body(request)).get("lang")
    if lang not in LANGS:
        return web.json_response({"error": "invalid_lang"}, status=400)
    user.lang = lang
    return web.json_response({"lang": lang})


async def terms(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    settings = request.app[SETTINGS_KEY]
    text = t(
        "pay.terms", locale=user.lang, free=settings.free_posts_per_day, **plans.trial_terms(settings),
    )
    return web.json_response({"html": text})


CALENDAR_DAYS = 7
CALENDAR_SNIPPET = 90
IDEA_SNIPPET = 140
IDEA_TEXT = 1500
MAX_MOVE_IDS = 50


def _parse_date(value: object) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _parse_hm(value: object) -> dt_time | None:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return None
    try:
        return dt_time(int(value[:2]), int(value[3:]))
    except ValueError:
        return None


def _calendar_item(pub: Publication, post: Post | None, channel: Channel, zone) -> dict:
    published = pub.status == "published"
    local = (pub.published_at if published else pub.run_at).astimezone(zone)
    first = post.parts[0] if post and post.parts else None
    ids = publication_message_ids(pub) if published else []
    return {
        "id": pub.id,
        "post_id": pub.post_id,
        "channel_id": pub.channel_id,
        "status": pub.status,
        "date": local.date().isoformat(),
        "time": local.strftime("%H:%M"),
        "icon": part_icon(first) if first else "📝",
        "text": snippet(part_preview_text(first), CALENDAR_SNIPPET) if first else "",
        "repeat": pub.repeat_index > 0 or bool(post and post.repeat and post.repeat.active),
        "link": message_link(channel, ids[0]) if ids else None,
    }


def _idea_item(post: Post) -> dict:
    first = post.parts[0] if post.parts else None
    text = part_preview_text(first) if first else ""
    return {
        "id": post.id,
        "icon": part_icon(first) if first else "📝",
        "text": snippet(text, IDEA_SNIPPET),
        "full": html_to_plain(text)[:IDEA_TEXT].strip(),
    }


async def _can_generate_ideas(request: web.Request, session: AsyncSession, user: User, channel: Channel) -> bool:
    """Generating ideas is a PRO tool: the channel's owner or an admin with settings rights, on a paid plan/trial."""
    ai = request.app.get(AI_KEY)
    if ai is None or not ai.enabled:
        return False
    if channel.owner_id != user.id and not await channel_admins_repo.has_permission(
        session, channel.id, user.id, "settings"
    ):
        return False
    return await ideas_service.can_generate(session, request.app[SETTINGS_KEY], channel)


async def _calendar_channel(session: AsyncSession, user: User, channel_id: object) -> Channel | None:
    """A channel `user` may post to."""
    if not _is_int(channel_id):
        return None
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    return next((c for c in channels if c.id == channel_id), None)


async def _idea_post(session: AsyncSession, user: User, post_id: object) -> Post | None:
    post = await posts_repo.get_post(session, user.id, post_id) if _is_int(post_id) else None
    return post if post is not None and ideas_service.is_idea(post) else None


async def calendar(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    """One week (Monday to Sunday, in the user's time zone) of queued and published posts."""
    now_local = local_now(user.tz)
    start = _parse_date(request.query.get("start")) or now_local.date()
    start -= timedelta(days=start.weekday())
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    by_id = {c.id: c for c in channels}
    channel_id = request.query.get("channel", "0")
    if not channel_id.isdigit() or (int(channel_id) and int(channel_id) not in by_id):
        return web.json_response({"error": "not_found"}, status=404)
    channel_ids = [int(channel_id)] if int(channel_id) else list(by_id)
    first, _ = day_bounds_utc(start, user.tz)
    _, last = day_bounds_utc(start + timedelta(days=CALENDAR_DAYS - 1), user.tz)
    pubs = await pubs_repo.calendar_between(session, user.id, first, last, channel_ids) if channel_ids else []
    post_ids = {p.post_id for p in pubs}
    posts = {}
    if post_ids:
        posts = {p.id: p for p in (await session.scalars(select(Post).where(Post.id.in_(post_ids)))).all()}
    zone = tz_of(user.tz)
    # Ideas belong to one channel: the selected one, or the only one the user has.
    selected = by_id.get(int(channel_id)) or (channels[0] if len(channels) == 1 else None)
    ideas = [_idea_item(p) for p in await ideas_service.for_channel(session, selected)] if selected else None
    return web.json_response({
        "lang": user.lang,
        "ideas": ideas,
        "ideas_channel": selected.id if selected else None,
        "ideas_enabled": bool(selected) and await _can_generate_ideas(request, session, user, selected),
        "start": start.isoformat(),
        "today": now_local.date().isoformat(),
        "now": now_local.hour * 60 + now_local.minute,
        "channels": [{"id": c.id, "title": c.title} for c in channels],
        "items": [_calendar_item(p, posts.get(p.post_id), by_id[p.channel_id], zone) for p in pubs],
    })


async def calendar_move(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    """Reschedule publications (a post's copies in several channels move together) to a local date and time."""
    body = await _json_body(request)
    ids, day, hm = body.get("ids"), _parse_date(body.get("date")), _parse_hm(body.get("time"))
    if (
        not isinstance(ids, list)
        or not 0 < len(ids) <= MAX_MOVE_IDS
        or not all(_is_int(i) for i in ids)
        or len(set(ids)) != len(ids)
        or day is None
        or hm is None
    ):
        return web.json_response({"error": "invalid_request"}, status=400)
    now = utcnow()
    run_at = to_utc(day, hm, user.tz)
    if run_at <= now:
        return web.json_response({"error": "past"}, status=400)
    if await pubs_repo.move_queued(session, user.id, ids, run_at, now) != len(ids):
        await session.rollback()
        return web.json_response({"error": "not_movable"}, status=409)
    return web.json_response({"ok": True})


async def generate_ideas(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    """A week of AI drafts for one channel, kept as its ideas until they're dragged onto the calendar."""
    channel = await _calendar_channel(session, user, (await _json_body(request)).get("channel_id"))
    if channel is None:
        return web.json_response({"error": "not_found"}, status=404)
    if channel.owner_id != user.id and not await channel_admins_repo.has_permission(
        session, channel.id, user.id, "settings"
    ):
        return web.json_response({"error": "forbidden", "message": t("err.not_found", locale=user.lang)}, status=403)
    try:
        texts = await ideas_service.generate(session, request.app[SETTINGS_KEY], request.app.get(AI_KEY), user, channel)
    except ideas_service.IdeasError as e:
        return web.json_response({"error": "ideas", "message": t(e.key, locale=user.lang)}, status=409)
    await ideas_service.save(session, channel, texts)
    return web.json_response({"ideas": [_idea_item(p) for p in await ideas_service.for_channel(session, channel)]})


async def schedule_idea(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    body = await _json_body(request)
    day, hm = _parse_date(body.get("date")), _parse_hm(body.get("time"))
    if day is None or hm is None:
        return web.json_response({"error": "invalid_request"}, status=400)
    post = await _idea_post(session, user, body.get("id"))
    if post is None:
        return web.json_response({"error": "not_found"}, status=404)
    run_at = to_utc(day, hm, user.tz)
    if run_at <= utcnow():
        return web.json_response({"error": "past"}, status=400)
    await ideas_service.schedule(session, user, post, run_at)
    return web.json_response({"ok": True})


async def delete_idea(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    post = await _idea_post(session, user, (await _json_body(request)).get("id"))
    if post is None:
        return web.json_response({"error": "not_found"}, status=404)
    await session.delete(post)
    return web.json_response({"ok": True})


def _page_html(name: str) -> str:
    """A page with asset URLs versioned by content, so Telegram's webview never serves a stale app.js."""
    digest = hashlib.sha256()
    for path in sorted(STATIC.iterdir()):
        if path.is_file():
            digest.update(path.read_bytes())
    return (STATIC / name).read_text(encoding="utf-8").replace("__V__", digest.hexdigest()[:12])


def setup_webapp(app: web.Application) -> None:
    def page(name: str) -> Callable[[web.Request], Awaitable[web.Response]]:
        html = _page_html(name)

        async def handler(_request: web.Request) -> web.Response:
            return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-cache"})

        return handler

    def redirect(to: str) -> Callable[[web.Request], Awaitable[web.Response]]:
        async def handler(request: web.Request) -> web.Response:
            raise web.HTTPFound(to + (f"?{request.query_string}" if request.query_string else ""))

        return handler

    app.router.add_get("/app", redirect("/app/"))
    app.router.add_get("/app/", page("index.html"))
    # The publishing calendar is its own Mini App, opened from a channel's card in the bot.
    app.router.add_get("/app/calendar", redirect("/app/calendar/"))
    app.router.add_get("/app/calendar/", page("calendar.html"))
    # The bot owner's panel: all channels and their limits; its API is in admin_api and checks ADMIN_IDS.
    app.router.add_get("/app/admin", redirect("/app/admin/"))
    app.router.add_get("/app/admin/", page("admin.html"))
    app.router.add_get("/app/giveaway", redirect("/app/giveaway/"))
    app.router.add_get("/app/giveaway/", page("giveaway.html"))
    app.router.add_static("/app/static/", STATIC)
    app.router.add_get("/api/bot-avatar", bot_avatar)
    app.router.add_get("/api/me", authed(me))
    app.router.add_post("/api/topup", authed(topup))
    app.router.add_post("/api/lang", authed(set_lang))
    app.router.add_get("/api/terms", authed(terms))
    app.router.add_get(r"/api/channels/{channel_id:\d+}", authed(channel_detail))
    app.router.add_get(r"/api/limits/{channel_id:\d+}", authed(limits_remaining))
    app.router.add_post("/api/limits", authed(buy_limits))
    app.router.add_post("/api/subscribe", authed(subscribe_channels))
    app.router.add_get("/api/transfer", authed(transfer_options))
    app.router.add_post("/api/transfer", authed(transfer_subscription))
    app.router.add_get("/api/calendar", authed(calendar))
    app.router.add_post("/api/calendar/move", authed(calendar_move))
    app.router.add_post("/api/ideas", authed(generate_ideas))
    app.router.add_post("/api/ideas/schedule", authed(schedule_idea))
    app.router.add_post("/api/ideas/delete", authed(delete_idea))
