"""Editor → «Опублікувати», «Скасувати і назад», and saving edits of already-published posts."""
from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InputMediaAnimation,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    LinkPreviewOptions,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from flowpost.bot.callbacks import Ed
from flowpost.bot.handlers.editor.view import close_editor, post_from_callback, show_panel
from flowpost.bot.keyboards.editor import confirm_kb
from flowpost.bot.keyboards.main_menu import main_menu_kb
from flowpost.db.models import Channel, Post, User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import publications as pubs_repo
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services.posts import build_markup, final_text, options_of, part_warnings, post_is_empty
from flowpost.services.worker import Worker

log = logging.getLogger(__name__)
router = Router(name="editor_publish")

INPUT_MEDIA = {
    "photo": InputMediaPhoto,
    "video": InputMediaVideo,
    "animation": InputMediaAnimation,
    "document": InputMediaDocument,
    "audio": InputMediaAudio,
}


async def publish_now(session: AsyncSession, worker: Worker, post: Post) -> str:
    """Publish into all target channels right away and return a human-readable report."""
    await pubs_repo.cancel_pending(session, post.id)
    pubs = await pubs_repo.create_publications(session, post, utcnow(), status="publishing", notify=False)
    pub_ids = [p.id for p in pubs]
    await session.commit()
    lines = [t("pub.result_title")]
    for pub_id in pub_ids:
        outcome = await worker.deliver(pub_id)
        if outcome.ok:
            lines.append(t("pub.ok_line", title=html.escape(outcome.channel_title), link=outcome.link or ""))
        else:
            lines.append(t("pub.fail_line", title=html.escape(outcome.channel_title), error=t(outcome.error or "err.unknown")))
        lines += ["⚠️ " + t(w) for w in outcome.warnings]
    return "\n".join(lines)


async def _validate(cb: CallbackQuery, session: AsyncSession, user: User, post: Post) -> bool:
    if post_is_empty(post):
        await cb.answer(t("err.post_empty"), show_alert=True)
        return False
    if not post.targets:
        await cb.answer(t("post.no_channels"), show_alert=True)
        return False
    channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
    opts = options_of(post)
    for channel in channels:
        for i, part in enumerate(post.parts):
            if "warn.text_too_long" in part_warnings(part, opts, channel, user.lang, is_last=i == len(post.parts) - 1):
                await cb.answer(t("warn.text_too_long"), show_alert=True)
                return False
    return True


@router.callback_query(Ed.filter(F.a == "pub"), flags={"paid": True})
async def ed_publish_ask(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None or not await _validate(cb, session, user, post):
        return
    await cb.answer()
    channels = await channels_repo.get_by_ids(session, user.id, post.channel_ids)
    names = ", ".join(html.escape(c.title) for c in channels)
    await show_panel(
        bot, cb.from_user.id, state, t("pub.confirm", n=len(channels), names=names),
        confirm_kb(post.id, "pubok", t("pub.confirm_yes")),
    )


@router.callback_query(Ed.filter(F.a == "pubok"), flags={"paid": True})
async def ed_publish(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
    worker: Worker,
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None or not await _validate(cb, session, user, post):
        return
    await cb.answer(t("pub.working"))
    await show_panel(bot, cb.from_user.id, state, t("pub.working"), None)
    report = await publish_now(session, worker, post)
    await show_panel(bot, cb.from_user.id, state, report, None)
    await state.clear()


@router.callback_query(Ed.filter(F.a.in_({"cancel", "cancelok", "exit"})))
async def ed_cancel(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        await state.clear()
        return
    is_draft = post.status == "draft"
    if callback_data.a == "cancel" and is_draft and not post_is_empty(post):
        await cb.answer()
        await show_panel(bot, cb.from_user.id, state, t("cancel.confirm"), confirm_kb(post.id, "cancelok", t("cancel.yes")))
        return
    await cb.answer()
    if is_draft:
        await session.delete(post)
        await session.flush()
    await close_editor(bot, cb.from_user.id, state, delete_preview=is_draft)
    key = "cancel.done" if is_draft else "cancel.closed"
    await bot.send_message(cb.from_user.id, t(key), reply_markup=main_menu_kb())


async def _edit_published_part(bot: Bot, channel: Channel, rec: dict, part, text: str, warnings: list[str]) -> None:
    chat_id = channel.chat_id
    markup = build_markup(part.buttons)
    media_msgs = rec.get("media_msgs") or []
    host = rec.get("caption_msg") or rec.get("text_msg")
    markup_host = rec.get("markup_msg") or (host if markup else None)
    if markup and not markup_host:
        warnings.append("save.buttons_album")

    async def run(coro) -> None:
        try:
            await coro
        except TelegramBadRequest as e:
            if "not modified" not in str(e):
                raise

    if part.media and len(part.media) == len(media_msgs):
        for mid, item in zip(media_msgs, part.media):
            cls = INPUT_MEDIA[item["type"]]
            caption = text if mid == rec.get("caption_msg") else None
            await run(bot.edit_message_media(
                media=cls(media=item["file_id"], caption=caption), chat_id=chat_id, message_id=mid,
                reply_markup=markup if mid == markup_host else None,
            ))
    elif part.media or media_msgs:
        warnings.append("save.media_count")
        if rec.get("caption_msg"):
            await run(bot.edit_message_caption(
                chat_id=chat_id, message_id=rec["caption_msg"], caption=text,
                reply_markup=markup if rec["caption_msg"] == markup_host else None,
            ))
    if rec.get("text_msg"):
        await run(bot.edit_message_text(
            text=text or "🔗", chat_id=chat_id, message_id=rec["text_msg"],
            reply_markup=markup if rec["text_msg"] == markup_host else None,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        ))
    rec["markup_msg"] = markup_host if markup else None


@router.callback_query(Ed.filter(F.a == "save"))
async def ed_save_published(
    cb: CallbackQuery, callback_data: Ed, bot: Bot, session: AsyncSession, state: FSMContext, user: User
) -> None:
    post, _ = await post_from_callback(cb, session, user, state, callback_data.p)
    if post is None:
        return
    await cb.answer(t("save.working"))
    opts = options_of(post)
    lines = [t("save.title")]
    for pub in await pubs_repo.published_for_post(session, post.id):
        channel = await session.get(Channel, pub.channel_id)
        if channel is None:
            continue
        warnings: list[str] = []
        records = (pub.message_ids or {}).get("parts", [])
        try:
            for i, part in enumerate(post.parts):
                if i >= len(records):
                    warnings.append("save.parts_added")
                    break
                text = final_text(part.text_html, opts, channel, is_last=i == len(post.parts) - 1, lang=user.lang)
                await _edit_published_part(bot, channel, records[i], part, text, warnings)
            flag_modified(pub, "message_ids")
            lines.append(t("save.ok_line", title=html.escape(channel.title)))
        except TelegramAPIError as e:
            log.info("edit published failed: %s", e)
            lines.append(t("pub.fail_line", title=html.escape(channel.title), error=html.escape(str(e))))
        lines += ["⚠️ " + t(w) for w in dict.fromkeys(warnings)]
    await show_panel(bot, cb.from_user.id, state, "\n".join(lines), confirm_kb(post.id, "exit", t("ed.exit")))
