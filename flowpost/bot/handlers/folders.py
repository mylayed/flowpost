"""«Інтерфейс → Папки»: user-defined groups of channels that narrow the channel pickers."""
from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Fd, St
from flowpost.bot.keyboards.common import btn, chunked, markup
from flowpost.bot.states import FolderInput
from flowpost.db.models import Channel, ChannelFolder, User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import folders as folders_repo
from flowpost.i18n import t

router = Router(name="folders")

ICONS = [
    "📂", "🗂", "📚", "🛡", "💲",
    "👥", "🏢", "🛒", "💳", "📍",
    "☁️", "🗺", "📖", "🎓", "👕",
    "🎭", "🏆", "🏋", "⚽", "🎾",
    "💊", "🛍", "💉", "🐾", "⛰",
    "🌤", "☀️", "🛋", "💡", "🍔",
    "🍴", "🍸", "⏰", "🚚", "⛵",
]
# Bot API 9.4 button styles; "" is the client's default look.
STYLES = ["", "primary", "success", "danger"]


def _label(channel: Channel, selected: bool) -> str:
    icon = "📢 " if channel.kind == "channel" else "👥 "
    return icon + ("🔷 " if selected else "") + channel.title


async def folders_view(session: AsyncSession, user: User) -> tuple[str, InlineKeyboardMarkup]:
    folders = await folders_repo.list_folders(session, user.id)
    counts = await folders_repo.counts_by_folder(session, user.id)
    rows = [
        [btn(t("fld.row", icon=f.icon, title=f.title, n=counts.get(f.id, 0)), Fd(a="open", f=f.id), f.style)]
        for f in folders
    ]
    rows.append([btn(t("fld.new"), Fd(a="new"))])
    rows.append([btn(t("btn.back"), St(a="ui"))])
    return t("fld.title") + "\n\n" + t("fld.help"), markup(rows)


async def edit_view(
    session: AsyncSession, user: User, folder: ChannelFolder, selected: set[int]
) -> tuple[str, InlineKeyboardMarkup]:
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    saved = set(await folders_repo.folder_channel_ids(session, folder.id))
    rows = [[btn(t("fld.clear") if selected else t("fld.select_all"), Fd(a="all", f=folder.id))]]
    rows += chunked(
        [btn(_label(c, c.id in selected), Fd(a="tog", f=folder.id, c=c.id)) for c in channels], 2
    )
    if selected == saved:
        rows.append([btn(t("btn.back"), Fd(a="list")), btn(t("fld.settings"), Fd(a="set", f=folder.id))])
    else:
        rows.append([btn(t("fld.cancel_back"), Fd(a="list")), btn(t("fld.save"), Fd(a="save", f=folder.id))])
    text = t("fld.pick_title", icon=folder.icon, title=html.escape(folder.title)) + "\n\n"
    text += t("fld.pick") if channels else t("fld.no_channels")
    return text, markup(rows)


def customize_view(folder: ChannelFolder) -> tuple[str, InlineKeyboardMarkup]:
    rows = chunked([btn(icon, Fd(a="ico", f=folder.id, v=icon)) for icon in ICONS], 5)
    rows.append([
        btn("✅" if s == (folder.style or "") else "◯", Fd(a="sty", f=folder.id, v=s), s or None)
        for s in STYLES
    ])
    rows.append([btn(t("btn.back"), Fd(a="open", f=folder.id)), btn(t("fld.delete"), Fd(a="del", f=folder.id))])
    text = (
        t("fld.cz_title") + "\n\n" + t("fld.cz_folder")
        + f"\n<blockquote>{html.escape(folder.icon)} {html.escape(folder.title)}</blockquote>\n\n"
        + t("fld.cz_hint")
    )
    return text, markup(rows)


def _is_icon(text: str) -> bool:
    """A short pictographic message (an emoji) sets the folder's icon; anything else renames it."""
    return 0 < len(text) <= 8 and not any(c.isalnum() or c.isspace() for c in text)


async def _edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None) -> None:
    if cb.message is None:
        return
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await cb.message.answer(text, reply_markup=kb)


async def _pending(
    state: FSMContext, session: AsyncSession, folder: ChannelFolder
) -> set[int]:
    """The in-progress selection for `folder`; falls back to what is saved when the screen is stale."""
    data = await state.get_data()
    if data.get("fld_id") == folder.id:
        return set(data.get("fld_sel") or [])
    selected = set(await folders_repo.folder_channel_ids(session, folder.id))
    await state.update_data(fld_id=folder.id, fld_sel=sorted(selected))
    return selected


@router.callback_query(St.filter(F.a == "ui_folders"))
async def st_folders(cb: CallbackQuery, session: AsyncSession, state: FSMContext, user: User) -> None:
    await state.clear()
    await cb.answer()
    await _edit(cb, *await folders_view(session, user))


@router.callback_query(Fd.filter(F.a == "list"))
async def fd_list(cb: CallbackQuery, session: AsyncSession, state: FSMContext, user: User) -> None:
    await state.clear()
    await cb.answer()
    await _edit(cb, *await folders_view(session, user))


@router.callback_query(Fd.filter(F.a == "new"))
async def fd_new(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(FolderInput.title)
    await _edit(
        cb,
        t("fld.create_title") + "\n\n" + t("fld.create_prompt"),
        markup([[btn(t("btn.back"), Fd(a="list"))]]),
    )


@router.message(FolderInput.title, F.text)
async def in_folder_title(message: Message, session: AsyncSession, state: FSMContext, user: User) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer(t("fld.name_empty"))
        return
    folder = await folders_repo.create_folder(session, user.id, title)
    await state.set_data({"fld_id": folder.id, "fld_sel": []})
    await state.set_state(None)
    await message.answer(t("fld.created", title=html.escape(folder.title)))
    text, kb = await edit_view(session, user, folder, set())
    await message.answer(text, reply_markup=kb)


@router.callback_query(Fd.filter(F.a == "open"))
async def fd_open(
    cb: CallbackQuery, callback_data: Fd, session: AsyncSession, state: FSMContext, user: User
) -> None:
    folder = await folders_repo.get_folder(session, user.id, callback_data.f)
    if folder is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    await cb.answer()
    await state.set_state(None)
    selected = set(await folders_repo.folder_channel_ids(session, folder.id))
    await state.update_data(fld_id=folder.id, fld_sel=sorted(selected))
    await _edit(cb, *await edit_view(session, user, folder, selected))


@router.callback_query(Fd.filter(F.a.in_({"tog", "all"})))
async def fd_toggle(
    cb: CallbackQuery, callback_data: Fd, session: AsyncSession, state: FSMContext, user: User
) -> None:
    folder = await folders_repo.get_folder(session, user.id, callback_data.f)
    if folder is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    selected = await _pending(state, session, folder)
    if callback_data.a == "all":
        channels = await channels_repo.list_channels(session, user.id, perm="posts")
        selected = set() if selected else {c.id for c in channels}
    elif callback_data.c in selected:
        selected.discard(callback_data.c)
    else:
        selected.add(callback_data.c)
    await state.update_data(fld_sel=sorted(selected))
    await cb.answer()
    await _edit(cb, *await edit_view(session, user, folder, selected))


@router.callback_query(Fd.filter(F.a == "save"))
async def fd_save(
    cb: CallbackQuery, callback_data: Fd, session: AsyncSession, state: FSMContext, user: User
) -> None:
    folder = await folders_repo.get_folder(session, user.id, callback_data.f)
    if folder is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    selected = await _pending(state, session, folder)
    channels = await channels_repo.list_channels(session, user.id, perm="posts")
    await folders_repo.set_folder_channels(session, folder.id, [c.id for c in channels if c.id in selected])
    await state.clear()
    await cb.answer(t("fld.saved"))
    await _edit(cb, *await folders_view(session, user))


@router.callback_query(Fd.filter(F.a.in_({"set", "ico", "sty"})))
async def fd_customize(
    cb: CallbackQuery, callback_data: Fd, session: AsyncSession, state: FSMContext, user: User
) -> None:
    folder = await folders_repo.get_folder(session, user.id, callback_data.f)
    if folder is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    if callback_data.a == "ico" and callback_data.v in ICONS:
        folder.icon = callback_data.v
        await session.flush()
    elif callback_data.a == "sty" and callback_data.v in STYLES:
        folder.style = callback_data.v or None
        await session.flush()
    await cb.answer()
    await state.set_state(FolderInput.customize)
    await state.update_data(fld_id=folder.id)
    await _edit(cb, *customize_view(folder))


@router.message(FolderInput.customize, F.text)
async def in_folder_customize(message: Message, session: AsyncSession, state: FSMContext, user: User) -> None:
    value = (message.text or "").strip()
    folder = await folders_repo.get_folder(session, user.id, (await state.get_data()).get("fld_id") or 0)
    if folder is None:
        await state.clear()
        await message.answer(t("err.not_found"))
        return
    if not value:
        await message.answer(t("fld.name_empty"))
        return
    if _is_icon(value):
        folder.icon = value
    else:
        folder.title = value[:folders_repo.TITLE_LIMIT]
    await session.flush()
    text, kb = customize_view(folder)
    await message.answer(text, reply_markup=kb)


@router.callback_query(Fd.filter(F.a.in_({"del", "delok"})))
async def fd_delete(
    cb: CallbackQuery, callback_data: Fd, session: AsyncSession, state: FSMContext, user: User
) -> None:
    folder = await folders_repo.get_folder(session, user.id, callback_data.f)
    if folder is None:
        await cb.answer(t("err.not_found"), show_alert=True)
        return
    if callback_data.a == "del":
        await cb.answer()
        await _edit(cb, t("fld.delete_confirm", title=html.escape(folder.title)), markup([
            [btn(t("fld.delete_yes"), Fd(a="delok", f=folder.id))],
            [btn(t("btn.back"), Fd(a="set", f=folder.id))],
        ]))
        return
    await folders_repo.delete_folder(session, folder)
    await state.clear()
    await cb.answer(t("fld.deleted"))
    await _edit(cb, *await folders_view(session, user))
