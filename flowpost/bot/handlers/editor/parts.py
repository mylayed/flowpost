"""Editor → «Повідомлення»: a series of several messages published one after another."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.view import post_from_callback, render_editor, show_panel
from flowpost.bot.keyboards.common import btn, markup
from flowpost.db.models import User
from flowpost.db.repo import posts as posts_repo
from flowpost.i18n import t
from flowpost.services.html_sanitize import snippet
from flowpost.services.posts import part_icon
from flowpost.services.publisher import Publisher

router = Router(name="editor_parts")
MAX_PARTS = 10


@router.callback_query(Ed.filter(F.a == "parts"))
async def ed_parts_menu(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer()
    p = post.id
    lines = [t("parts.title", n=len(post.parts)), "", t("parts.help")]
    rows = []
    for i, part in enumerate(post.parts):
        label = f"{'👉 ' if i == idx else ''}{i + 1}. {part_icon(part)} {snippet(part.text_html, 28) or t('parts.no_text')}"
        rows.append([btn(label, Ed(a="part", p=p, v=str(i)))])
    if len(post.parts) < MAX_PARTS:
        rows.append([btn(t("parts.add"), Ed(a="pt_add", p=p))])
    if len(post.parts) > 1:
        rows.append([btn(t("parts.delete", n=idx + 1), Ed(a="pt_del", p=p))])
    rows.append([btn(t("btn.back"), Ed(a="home", p=p))])
    await show_panel(bot, cb.from_user.id, state, "\n".join(lines), markup(rows))


@router.callback_query(Ed.filter(F.a.in_({"pt_add", "pt_del"})))
async def ed_parts_change(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    publisher: Publisher,
) -> None:
    post, idx = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    if callback_data.a == "pt_add":
        if len(post.parts) >= MAX_PARTS:
            await cb.answer(t("parts.limit", max=MAX_PARTS), show_alert=True)
            return
        posts_repo.add_part(post)
        new_idx = len(post.parts) - 1
        note = t("parts.added", n=new_idx + 1)
    else:
        posts_repo.remove_part(post, idx)
        new_idx = max(0, idx - 1)
        note = t("parts.deleted")
    await session.flush()
    await cb.answer()
    await state.update_data(part=new_idx)
    await render_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=note)
