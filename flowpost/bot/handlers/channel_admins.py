"""«Мої проєкти» → канал → «Адміністратори»: invite links and managing delegated access."""
from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ca, Pj
from flowpost.bot.keyboards.common import btn, markup, on
from flowpost.db.models import Channel, ChannelAdmin, User
from flowpost.db.repo import channel_admins as channel_admins_repo
from flowpost.i18n import t

router = Router(name="channel_admins")

PERM_KEYS = ("posts", "settings", "disconnect")
DEFAULT_PERMS = "100"  # posts on, settings/disconnect off


async def _edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None) -> None:
    if cb.message is None:
        return
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await cb.message.answer(text, reply_markup=kb)


def _perm_labels(bits: str, locale: str | None = None) -> list[str]:
    return [t(f"admins.perm_{key}", locale=locale) for key, bit in zip(PERM_KEYS, bits) if bit == "1"]


def _admin_name(user: User) -> str:
    return html.escape(user.first_name or (f"@{user.username}" if user.username else str(user.tg_id)))


async def _owner_channel(session: AsyncSession, user: User, channel_id: int) -> Channel | None:
    return await session.scalar(select(Channel).where(Channel.id == channel_id, Channel.owner_id == user.id))


async def list_screen(session: AsyncSession, channel: Channel) -> tuple[str, InlineKeyboardMarkup]:
    admins = await channel_admins_repo.list_admins(session, channel.id)
    lines = [t("admins.list_title", title=html.escape(channel.title)), ""]
    rows: list[list] = []
    if admins:
        for grant, admin_user in admins:
            name = _admin_name(admin_user)
            lines.append(f"👤 {name} — {', '.join(_perm_labels(_grant_bits(grant))) or '—'}")
            rows.append([btn(f"👤 {name}", Ca(a="admin", c=channel.id, id=grant.id))])
    else:
        lines.append(t("admins.list_empty"))
    rows.append([btn(t("admins.invite_btn"), Ca(a="new", c=channel.id, v=DEFAULT_PERMS))])
    rows.append([btn(t("btn.back"), Pj(a="ch", c=channel.id))])
    return "\n".join(lines), markup(rows)


def new_screen(channel: Channel, bits: str) -> tuple[str, InlineKeyboardMarkup]:
    rows = [
        [btn(("✅ " if bits[i] == "1" else "") + t(f"admins.perm_{key}"), Ca(a="toggle", c=channel.id, id=i, v=bits))]
        for i, key in enumerate(PERM_KEYS)
    ]
    rows.append([btn(t("admins.new_create"), Ca(a="create", c=channel.id, v=bits))])
    rows.append([btn(t("btn.back"), Ca(a="list", c=channel.id))])
    return t("admins.new_title", title=html.escape(channel.title)) + "\n\n" + t("admins.perms_help"), markup(rows)


def _grant_bits(grant: ChannelAdmin) -> str:
    return "".join("1" if getattr(grant, f"can_{k}") else "0" for k in PERM_KEYS)


def admin_screen(channel: Channel, grant: ChannelAdmin, admin_user: User | None) -> tuple[str, InlineKeyboardMarkup]:
    """One administrator: their permissions toggle right here, and a way to take access away."""
    bits = _grant_bits(grant)
    rows = [
        [btn(on(bits[i] == "1") + t(f"admins.perm_{key}"), Ca(a="perm", c=channel.id, id=grant.id, v=key))]
        for i, key in enumerate(PERM_KEYS)
    ]
    rows.append([btn(t("admins.remove_btn"), Ca(a="remove", c=channel.id, id=grant.id))])
    rows.append([btn(t("btn.back"), Ca(a="list", c=channel.id))])
    name = _admin_name(admin_user) if admin_user else "?"
    text = t("admins.edit_title", name=name, title=html.escape(channel.title)) + "\n\n" + t("admins.perms_help")
    return text, markup(rows)


async def _channel_grant(
    cb: CallbackQuery, session: AsyncSession, user: User, callback_data: Ca
) -> tuple[Channel, ChannelAdmin] | None:
    """The owner's channel and one of its administrators, or None after telling the user it's gone."""
    channel = await _owner_channel(session, user, callback_data.c)
    grant = await session.get(ChannelAdmin, callback_data.id) if channel is not None else None
    if channel is None or grant is None or grant.channel_id != channel.id:
        await cb.answer(t("err.not_found"), show_alert=True)
        return None
    return channel, grant


@router.callback_query(Ca.filter(F.a == "list"))
async def ca_list(cb: CallbackQuery, callback_data: Ca, session: AsyncSession, user: User) -> None:
    channel = await _owner_channel(session, user, callback_data.c)
    if channel is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    await cb.answer()
    await _edit(cb, *await list_screen(session, channel))


@router.callback_query(Ca.filter(F.a == "new"))
async def ca_new(cb: CallbackQuery, callback_data: Ca, session: AsyncSession, user: User) -> None:
    channel = await _owner_channel(session, user, callback_data.c)
    if channel is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    await cb.answer()
    await _edit(cb, *new_screen(channel, callback_data.v or DEFAULT_PERMS))


@router.callback_query(Ca.filter(F.a == "toggle"))
async def ca_toggle(cb: CallbackQuery, callback_data: Ca, session: AsyncSession, user: User) -> None:
    channel = await _owner_channel(session, user, callback_data.c)
    if channel is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    bits = list(callback_data.v or DEFAULT_PERMS)
    if 0 <= callback_data.id < len(bits):
        bits[callback_data.id] = "0" if bits[callback_data.id] == "1" else "1"
    await cb.answer()
    await _edit(cb, *new_screen(channel, "".join(bits)))


@router.callback_query(Ca.filter(F.a == "create"))
async def ca_create(cb: CallbackQuery, callback_data: Ca, bot: Bot, session: AsyncSession, user: User) -> None:
    channel = await _owner_channel(session, user, callback_data.c)
    if channel is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    bits = callback_data.v or DEFAULT_PERMS
    if "1" not in bits:
        await cb.answer(t("admins.new_need_one"), show_alert=True)
        return
    invite = await channel_admins_repo.create_invite(
        session, channel.id, user.id,
        can_posts=bits[0] == "1", can_settings=bits[1] == "1", can_disconnect=bits[2] == "1",
    )
    await cb.answer()
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=adm_{invite.token}"
    text = t("admins.invite_created", link=link, perms=", ".join(_perm_labels(bits)))
    await _edit(cb, text, markup([[btn(t("btn.back"), Ca(a="list", c=channel.id))]]))


@router.callback_query(Ca.filter(F.a == "admin"))
async def ca_admin(cb: CallbackQuery, callback_data: Ca, session: AsyncSession, user: User) -> None:
    found = await _channel_grant(cb, session, user, callback_data)
    if found is None:
        return
    channel, grant = found
    await cb.answer()
    await _edit(cb, *admin_screen(channel, grant, await session.get(User, grant.user_id)))


@router.callback_query(Ca.filter(F.a == "perm"))
async def ca_perm(cb: CallbackQuery, callback_data: Ca, bot: Bot, session: AsyncSession, user: User) -> None:
    """Turn one permission of an existing administrator on or off; they're told what they can do now."""
    found = await _channel_grant(cb, session, user, callback_data)
    if found is None or callback_data.v not in PERM_KEYS:
        return
    channel, grant = found
    column = f"can_{callback_data.v}"
    setattr(grant, column, not getattr(grant, column))
    bits = _grant_bits(grant)
    if "1" not in bits:
        setattr(grant, column, True)
        await cb.answer(t("admins.edit_need_one"), show_alert=True)
        return
    await session.flush()
    await cb.answer()
    admin_user = await session.get(User, grant.user_id)
    await _edit(cb, *admin_screen(channel, grant, admin_user))
    if admin_user is not None and not admin_user.is_blocked:
        perms = ", ".join(_perm_labels(bits, admin_user.lang))
        try:
            await bot.send_message(
                admin_user.tg_id,
                t("admins.perms_changed", locale=admin_user.lang, title=html.escape(channel.title), perms=perms),
            )
        except TelegramAPIError:
            pass


@router.callback_query(Ca.filter(F.a.in_({"remove", "removeok"})))
async def ca_remove(cb: CallbackQuery, callback_data: Ca, session: AsyncSession, user: User) -> None:
    found = await _channel_grant(cb, session, user, callback_data)
    if found is None:
        return
    channel, grant = found
    admin_user = await session.get(User, grant.user_id)
    name = _admin_name(admin_user) if admin_user else "?"
    if callback_data.a == "remove":
        await cb.answer()
        kb = markup([
            [btn(t("admins.remove_yes"), Ca(a="removeok", c=channel.id, id=grant.id))],
            [btn(t("btn.back"), Ca(a="admin", c=channel.id, id=grant.id))],
        ])
        await _edit(cb, t("admins.remove_confirm", name=name, title=html.escape(channel.title)), kb)
        return
    await channel_admins_repo.remove_admin(session, channel.id, grant.id)
    await cb.answer(t("admins.removed"))
    await _edit(cb, *await list_screen(session, channel))
