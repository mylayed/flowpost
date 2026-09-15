"""JSON API behind the billing Mini App; every /api request is authenticated with Telegram initData."""
from __future__ import annotations

import hashlib
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from aiogram.exceptions import TelegramAPIError
from aiogram.types import User as TgUser
from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.config import Settings
from flowpost.db.models import Channel, User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import users as users_repo
from flowpost.db.types import utcnow
from flowpost.i18n import LANGS, t
from flowpost.services.billing import channel_subs, entitlements, limits, plans
from flowpost.services.billing.stars import create_topup_link
from flowpost.services.posts import channel_link
from flowpost.webapp import BOT_KEY, SESSIONMAKER_KEY, SETTINGS_KEY
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
    """The channel's plan, validity and posts left, as shown in the Mini App."""
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


async def owned_channel(session: AsyncSession, user: User, channel_id: int) -> Channel | None:
    channel = await session.get(Channel, channel_id)
    if channel is None or channel.owner_id != user.id or not channel.is_active:
        return None
    return channel


async def channel_detail(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    channel = await owned_channel(session, user, int(request.match_info["channel_id"]))
    if channel is None:
        return web.json_response({"error": "not_found"}, status=404)
    return web.json_response({
        "id": channel.id,
        "title": channel.title,
        "username": channel.username,
        "link": channel_link(channel),
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
        "pay.terms", locale=user.lang, days=settings.trial_days, posts=settings.trial_posts,
        free=settings.free_posts_per_day,
    )
    return web.json_response({"html": text})


def _index_html() -> str:
    """index.html with asset URLs versioned by content, so Telegram's webview never serves a stale app.js."""
    digest = hashlib.sha256()
    for path in sorted(STATIC.iterdir()):
        if path.is_file():
            digest.update(path.read_bytes())
    return (STATIC / "index.html").read_text(encoding="utf-8").replace("__V__", digest.hexdigest()[:12])


def setup_webapp(app: web.Application) -> None:
    html = _index_html()

    async def index(_request: web.Request) -> web.Response:
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-cache"})

    async def to_index(_request: web.Request) -> web.Response:
        raise web.HTTPFound("/app/")

    app.router.add_get("/app", to_index)
    app.router.add_get("/app/", index)
    app.router.add_static("/app/static/", STATIC)
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
