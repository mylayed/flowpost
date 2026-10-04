"""The bot owner's Mini App (/app/admin/): every connected channel with its plan and limits, and granting
quotas or plan days to a channel — extra, or as compensation. Only users from ADMIN_IDS get through."""
from __future__ import annotations

import html
import logging

from aiogram.exceptions import TelegramAPIError
from aiohttp import web
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Channel, UsageEvent, User
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services import analytics
from flowpost.services.billing import channel_subs, limits
from flowpost.services.billing.unlimited import is_unlimited
from flowpost.webapp import BOT_KEY, SETTINGS_KEY
from flowpost.webapp.api import ApiHandler, _json_body, _is_int, authed, channel_info

log = logging.getLogger(__name__)

PAGE = 30
MAX_QUOTA_GRANT = 100_000
MAX_DAYS_GRANT = 3650
MAX_NOTE = 500
GRANT_EVENT = "admin_grant"
HISTORY = 50


def admin_only(fn: ApiHandler):
    async def guarded(request: web.Request, session: AsyncSession, user: User) -> web.StreamResponse:
        if user.tg_id not in request.app[SETTINGS_KEY].admin_id_set:
            return web.json_response({"error": "forbidden"}, status=403)
        return await fn(request, session, user)

    return authed(guarded)


def _search(q: str):
    like = f"%{q.lstrip('@')}%"
    conditions = [
        Channel.title.ilike(like),
        func.coalesce(Channel.username, "").ilike(like),
        func.coalesce(User.username, "").ilike(like),
        func.coalesce(User.first_name, "").ilike(like),
    ]
    digits = q.lstrip("-@")
    if digits.isdigit():
        conditions += [cast(Channel.chat_id, String).like(f"%{digits}%"), cast(User.tg_id, String) == digits]
    return or_(*conditions)


async def _item(session: AsyncSession, request: web.Request, channel: Channel, owner: User) -> dict:
    settings = request.app[SETTINGS_KEY]
    now = utcnow()
    sub = await channel_subs.get(session, channel.id)
    return {
        "id": channel.id,
        "chat_id": channel.chat_id,
        "title": channel.title,
        "username": channel.username,
        "kind": channel.kind,
        "connected_at": channel.created_at.isoformat() if channel.created_at else None,
        "trial_ends_at": channel.trial_ends_at.isoformat() if channel.trial_ends_at else None,
        "sub_posts_per_day": sub.posts_per_day if sub is not None and sub.paid_until > now else None,
        "owner": {"tg_id": owner.tg_id, "username": owner.username, "name": owner.first_name},
        "unlimited": is_unlimited(owner, settings),
        **await channel_info(session, settings, channel, owner, now),
    }


async def admin_channels(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    q = (request.query.get("q") or "").strip()[:64]
    try:
        offset = max(0, int(request.query.get("offset", "0")))
    except ValueError:
        offset = 0
    query = select(Channel, User).join(User, User.id == Channel.owner_id).where(Channel.is_active.is_(True))
    if q:
        query = query.where(_search(q))
    total = int(await session.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = (await session.execute(query.order_by(Channel.created_at.desc(), Channel.id.desc())
                                  .offset(offset).limit(PAGE))).all()
    items = [await _item(session, request, channel, owner) for channel, owner in rows]
    return web.json_response({"total": total, "offset": offset, "page": PAGE, "items": items})


async def admin_meta(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    settings = request.app[SETTINGS_KEY]
    return web.json_response({"kinds": list(limits.LIMIT_KINDS), "plans": sorted(settings.posting_plans)})


def _parse_grant(body: dict, plans: dict) -> tuple[dict[str, int], int, int | None] | str:
    quotas = body.get("quotas") or {}
    if not isinstance(quotas, dict):
        return "invalid_quotas"
    parsed = {}
    for kind, amount in quotas.items():
        if kind not in limits.LIMIT_KINDS or not _is_int(amount) or not 0 <= amount <= MAX_QUOTA_GRANT:
            return "invalid_quotas"
        if amount:
            parsed[kind] = amount
    days = body.get("days") or 0
    if not _is_int(days) or not 0 <= days <= MAX_DAYS_GRANT:
        return "invalid_days"
    posts_per_day = body.get("posts_per_day")
    if days and posts_per_day not in plans:
        return "invalid_plan"
    if not parsed and not days:
        return "nothing_to_grant"
    return parsed, days, posts_per_day if days else None


async def admin_grant(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    settings = request.app[SETTINGS_KEY]
    body = await _json_body(request)
    channel_id = body.get("channel_id")
    channel = await session.get(Channel, channel_id) if _is_int(channel_id) else None
    if channel is None:
        return web.json_response({"error": "not_found"}, status=404)
    parsed = _parse_grant(body, settings.posting_plans)
    if isinstance(parsed, str):
        return web.json_response({"error": parsed}, status=400)
    quotas, days, posts_per_day = parsed
    note = str(body.get("note") or "").strip()[:MAX_NOTE]

    for kind, amount in quotas.items():
        await limits.add(session, channel.id, kind, amount)
    if days:
        await channel_subs.grant(session, settings, channel.id, posts_per_day, days)
    await session.flush()
    # The grant's record is also the channel's grant history in the panel.
    event = analytics.track(session, user.id, GRANT_EVENT, channel_id=channel.id, quotas=quotas, days=days,
                            posts_per_day=posts_per_day, note=note, notified=False)
    owner = await session.get(User, channel.owner_id)
    await session.commit()

    notified = False
    if body.get("notify") and owner is not None and not owner.is_blocked:
        notified = await _notify_owner(request, owner, channel, quotas, days, posts_per_day, note)
        event.meta = {**event.meta, "notified": notified}
    return web.json_response({"ok": True, "notified": notified, "item": await _item(session, request, channel, owner)})


async def _notify_owner(
    request: web.Request, owner: User, channel: Channel, quotas: dict[str, int], days: int,
    posts_per_day: int | None, note: str,
) -> bool:
    lang = owner.lang
    lines = [t(f"grant.kind_{kind}", locale=lang, n=amount) for kind, amount in quotas.items()]
    if days:
        lines.append(t("grant.days", locale=lang, n=days, posts=posts_per_day))
    text = t("notify.grant", locale=lang, title=html.escape(channel.title), items="\n".join(lines))
    if note:
        text += "\n\n" + t("notify.grant_note", locale=lang, note=html.escape(note))
    try:
        await request.app[BOT_KEY].send_message(owner.tg_id, text)
    except TelegramAPIError as e:
        log.info("grant notice not delivered: %s", e)
        return False
    return True


async def admin_grants(request: web.Request, session: AsyncSession, user: User) -> web.Response:
    """The channel's grant history, newest first. Grants are made by ADMIN_IDS only, so the lookup goes through
    their user ids and the (user_id, kind, created_at) index rather than scanning every usage event."""
    settings = request.app[SETTINGS_KEY]
    channel_id = int(request.match_info["channel_id"])
    admins = {u.id: u for u in await session.scalars(select(User).where(User.tg_id.in_(settings.admin_id_set)))}
    if not admins:
        return web.json_response({"items": []})
    events = await session.scalars(
        select(UsageEvent)
        .where(
            UsageEvent.user_id.in_(admins), UsageEvent.kind == GRANT_EVENT,
            UsageEvent.meta["channel_id"].as_integer() == channel_id,
        )
        .order_by(UsageEvent.created_at.desc(), UsageEvent.id.desc())
        .limit(HISTORY)
    )
    items = []
    for event in events:
        meta, by = event.meta or {}, admins[event.user_id]
        items.append({
            "at": event.created_at.isoformat(),
            "by": {"tg_id": by.tg_id, "name": by.first_name, "username": by.username},
            "quotas": meta.get("quotas") or {},
            "days": meta.get("days") or 0,
            "posts_per_day": meta.get("posts_per_day"),
            "note": meta.get("note") or "",
            "notified": meta.get("notified"),
        })
    return web.json_response({"items": items})


def setup_admin_api(app: web.Application) -> None:
    app.router.add_get(r"/api/admin/channels/{channel_id:\d+}/grants", admin_only(admin_grants))
    app.router.add_get("/api/admin/meta", admin_only(admin_meta))
    app.router.add_get("/api/admin/channels", admin_only(admin_channels))
    app.router.add_post("/api/admin/grant", admin_only(admin_grant))
