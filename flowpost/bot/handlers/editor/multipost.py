"""Editor → «Мультипостинг»: publish one post into several connected channels."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.view import post_from_callback, show_panel
from flowpost.bot.keyboards.common import btn, markup, on
from flowpost.db.models import User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.i18n import t

router = Router(name="editor_multipost")


@router.callback_query(Ed.filter(F.a.in_({"multi", "mt"})))
async def ed_multipost(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    channels = await channels_repo.list_channels(session, user.id)
    selected = list(post.channel_ids)
    if callback_data.a == "mt" and callback_data.v.isdigit():
        cid = int(callback_data.v)
        if cid in selected:
            if len(selected) == 1:
                await cb.answer(t("multi.need_one"), show_alert=True)
                return
            selected.remove(cid)
        elif any(c.id == cid for c in channels):
            selected.append(cid)
        posts_repo.set_targets(post, selected)
        await session.flush()
    await cb.answer()
    p = post.id
    rows = [
        [btn(on(c.id in selected) + ("📢 " if c.kind == "channel" else "👥 ") + c.title, Ed(a="mt", p=p, v=str(c.id)))]
        for c in channels
    ]
    rows.append([btn(t("multi.done"), Ed(a="home", p=p))])
    text = t("multi.title", n=len(selected)) + "\n\n" + (t("multi.help") if len(channels) > 1 else t("multi.only_one"))
    await show_panel(bot, cb.from_user.id, state, text, markup(rows))
