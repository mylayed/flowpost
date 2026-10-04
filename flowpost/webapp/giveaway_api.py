"""The giveaway Mini App: whoever opens it from a giveaway's «Беру участь» button enters that giveaway.

The people tapping are the channel's readers, not FlowPost users, so the request is checked with initData but
no FlowPost account is created for them."""
from __future__ import annotations

from aiogram.types import User as TgUser
from aiohttp import web

from flowpost.i18n import detect_lang, t
from flowpost.services import giveaway
from flowpost.webapp import BOT_KEY, SESSIONMAKER_KEY, SETTINGS_KEY
from flowpost.webapp.api import AUTH_SCHEME, _json_body, open_link
from flowpost.webapp.auth import validate_init_data

MESSAGES = {
    "joined": "gwb.app_joined",
    "already": "gwb.app_already",
    "subscribe": "gwb.app_subscribe",
    "closed": "gwb.app_closed",
    "gone": "gwb.app_gone",
}


async def join(request: web.Request) -> web.Response:
    settings = request.app[SETTINGS_KEY]
    header = request.headers.get("Authorization", "")
    tg = (
        validate_init_data(header[len(AUTH_SCHEME):], settings.bot_token.get_secret_value())
        if header.startswith(AUTH_SCHEME)
        else None
    )
    if tg is None:
        return web.json_response({"error": "unauthorized"}, status=401)
    body = await _json_body(request)
    gw_id = giveaway.parse_start(str(body.get("start") or ""))
    lang = detect_lang(tg.get("language_code"))
    person = TgUser(id=tg["id"], is_bot=False, first_name=tg.get("first_name") or "", last_name=tg.get("last_name"),
                    username=tg.get("username"), language_code=tg.get("language_code"))
    bot = request.app[BOT_KEY]
    async with request.app[SESSIONMAKER_KEY]() as session:
        if gw_id is None:
            status, gw, channel = "gone", None, None
        else:
            status, gw, channel = await giveaway.join(bot, session, gw_id, person)
        out = {
            "status": status,
            "text": t(MESSAGES[status], locale=lang),
            "channel": channel.title if channel is not None else "",
            "count": gw.entries if gw is not None else 0,
        }
        if status == "subscribe" and channel is not None:
            out["channel_url"] = await open_link(bot, session, channel)
            out["open_label"] = t("gwb.app_open_channel", locale=lang)
            out["retry_label"] = t("gwb.app_retry", locale=lang)
        await session.commit()
    return web.json_response(out)


def setup_giveaway_api(app: web.Application) -> None:
    app.router.add_post("/api/giveaway/join", join)
