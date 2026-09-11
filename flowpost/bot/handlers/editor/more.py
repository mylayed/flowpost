"""Editor → «Більше налаштувань»: silent, protect, link preview, pin, auto-delete, ad label, topic."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Cs, Ed
from flowpost.bot.handlers.editor.view import load_editor_post, post_from_callback, render_editor, show_panel
from flowpost.bot.keyboards.common import btn, markup, on
from flowpost.bot.states import Editor
from flowpost.db.models import Channel, Post, User
from flowpost.db.repo import channels as channels_repo
from flowpost.i18n import t
from flowpost.services.parsing import ParseError, parse_positive_int
from flowpost.services.posts import options_of
from flowpost.services.publisher import Publisher

router = Router(name="editor_more")

TOGGLES = {"silent", "protect", "link_preview", "ad_label"}
PIN_CYCLE: list[tuple[bool, int | None]] = [(False, None), (True, None), (True, 24), (True, 48)]
DELETE_CYCLE: list[int | None] = [None, 1, 6, 12, 24, 48]
MAX_HOURS = 720


def _pin_label(opts: dict) -> str:
    if not opts["pin"]:
        return t("more.pin_off")
    return t("more.pin_hours", hours=opts["pin_hours"]) if opts["pin_hours"] else t("more.pin_forever")


def _delete_label(opts: dict) -> str:
    hours = opts["auto_delete_hours"]
    return t("more.delete_hours", hours=hours) if hours else t("more.delete_off")


def more_menu(post: Post, primary: Channel | None) -> tuple[str, object]:
    opts = options_of(post)
    p = post.id
    rows = [
        [btn(on(opts["silent"]) + t("more.silent"), Ed(a="mo_t", p=p, v="silent"))],
        [btn(on(opts["protect"]) + t("more.protect"), Ed(a="mo_t", p=p, v="protect"))],
        [btn(on(opts["link_preview"]) + t("more.link_preview"), Ed(a="mo_t", p=p, v="link_preview"))],
        [btn(_pin_label(opts), Ed(a="mo_pin", p=p)), btn(t("more.custom"), Ed(a="mo_pinc", p=p))],
        [btn(_delete_label(opts), Ed(a="mo_del", p=p)), btn(t("more.custom"), Ed(a="mo_delc", p=p))],
    ]
    if post.is_ad:
        rows.append([btn(on(opts["ad_label"]) + t("more.ad_label"), Ed(a="mo_t", p=p, v="ad_label"))])
    if primary is not None and primary.is_forum:
        rows.append([btn(t("btn.topic_set"), Cs(a="topic", c=primary.id, p=p))])
    rows.append([btn(t("btn.back"), Ed(a="home", p=p))])
    return t("more.title") + "\n\n" + t("more.help"), markup(rows)


async def _show(bot: Bot, chat_id: int, session: AsyncSession, state: FSMContext, user: User, post: Post) -> None:
    channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
    text, kb = more_menu(post, channels[0] if channels else None)
    await show_panel(bot, chat_id, state, text, kb)


@router.callback_query(Ed.filter(F.a.in_({"more", "mo_t", "mo_pin", "mo_del"})))
async def ed_more(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    opts = options_of(post)
    changes: dict = {}
    if callback_data.a == "mo_t" and callback_data.v in TOGGLES:
        changes[callback_data.v] = not opts[callback_data.v]
    elif callback_data.a == "mo_pin":
        current = (bool(opts["pin"]), opts["pin_hours"])
        nxt = PIN_CYCLE[(PIN_CYCLE.index(current) + 1) % len(PIN_CYCLE)] if current in PIN_CYCLE else PIN_CYCLE[0]
        changes.update(pin=nxt[0], pin_hours=nxt[1])
    elif callback_data.a == "mo_del":
        current = opts["auto_delete_hours"]
        nxt = DELETE_CYCLE[(DELETE_CYCLE.index(current) + 1) % len(DELETE_CYCLE)] if current in DELETE_CYCLE else None
        changes["auto_delete_hours"] = nxt
    if changes:
        post.options = {**(post.options or {}), **changes}
        await session.flush()
    await cb.answer()
    await state.set_state(Editor.content)
    await _show(bot, cb.from_user.id, session, state, user, post)


@router.callback_query(Ed.filter(F.a.in_({"mo_pinc", "mo_delc"})))
async def ed_more_custom(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    pin = callback_data.a == "mo_pinc"
    await state.set_state(Editor.pin_hours if pin else Editor.delete_hours)
    back = markup([[btn(t("btn.back"), Ed(a="more", p=post.id))]])
    await show_panel(
        bot, cb.from_user.id, state, t("more.pin_prompt" if pin else "more.delete_prompt", max=MAX_HOURS), back
    )


@router.message(Editor.pin_hours, F.text)
@router.message(Editor.delete_hours, F.text)
async def in_hours(
    message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User, publisher: Publisher
) -> None:
    post, _ = await load_editor_post(session, user, state)
    if post is None:
        await state.clear()
        await message.answer(t("err.post_not_found"))
        return
    try:
        hours = parse_positive_int(message.text or "", MAX_HOURS)
    except ParseError as e:
        await message.answer(t(e.key, **e.params))
        return
    if await state.get_state() == Editor.pin_hours.state:
        post.options = {**(post.options or {}), "pin": True, "pin_hours": hours}
        note = t("more.pin_hours", hours=hours)
    else:
        post.options = {**(post.options or {}), "auto_delete_hours": hours}
        note = t("more.delete_hours", hours=hours)
    await session.flush()
    await render_editor(bot, message.chat.id, session, state, user, post, publisher, note="✅ " + note)
