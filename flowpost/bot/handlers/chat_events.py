"""Updates from connected channels: join requests, people joining or leaving, «show hidden text» taps and taps on
a giveaway's «Беру участь» button (when no giveaway Mini App is set up)."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, ChatJoinRequest, ChatMemberUpdated
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Post, QuizVote, User
from flowpost.db.repo import channels as channels_repo
from flowpost.db.types import utcnow
from flowpost.i18n import detect_lang, t
from flowpost.services import giveaway, growth
from flowpost.services.posts import (
    GIVEAWAY_PREFIX, HIDDEN_BTN_PREFIX, HIDDEN_PREFIX, MAX_HIDDEN, QUIZ_PREFIX, find_hidden, options_of, quiz_answers,
    quiz_locked_text,
)

log = logging.getLogger(__name__)
router = Router(name="chat_events")

IN_CHAT = {"member", "administrator", "creator"}


def _is_in(member) -> bool:
    status = str(getattr(member, "status", ""))
    return status in IN_CHAT or (status == "restricted" and bool(getattr(member, "is_member", False)))


@router.chat_join_request()
async def on_join_request(request: ChatJoinRequest, bot: Bot, session: AsyncSession) -> None:
    channel = next(
        (c for c in await channels_repo.channels_by_chat(session, request.chat.id) if c.is_active and growth.handles_requests(c)),
        None,
    )
    if channel is None:
        return
    now = utcnow()
    url = request.invite_link.invite_link if request.invite_link else None
    row = await growth.queue_request(session, channel, request.from_user.id, url, now)
    if growth.join_settings(channel.join_settings)["welcome"]:
        lang = detect_lang(request.from_user.language_code)
        try:
            # Telegram lets the bot write to someone who asked to join, via user_chat_id, for a short while.
            await bot.send_message(request.user_chat_id, growth.welcome_text(channel, request.from_user.first_name, lang))
        except TelegramAPIError as e:
            log.info("welcome to %s not delivered: %s", request.from_user.id, e)
    if row.approve_at is not None and row.approve_at <= now:
        await growth.approve_request(bot, session, channel, row, now)


@router.chat_member()
async def on_member_change(update: ChatMemberUpdated, session: AsyncSession) -> None:
    was_in, is_in = _is_in(update.old_chat_member), _is_in(update.new_chat_member)
    user_id = update.new_chat_member.user.id
    now = utcnow()
    if not was_in and is_in:
        link = await growth.find_link(session, update.chat.id, update.invite_link.invite_link if update.invite_link else None)
        if link is not None:
            await growth.record_join(session, link, user_id, now)
    elif was_in and not is_in:
        await growth.record_leave(session, update.chat.id, user_id, now)


@router.callback_query(F.data.startswith(HIDDEN_PREFIX))
async def on_hidden_text(cb: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    lang = detect_lang(cb.from_user.language_code)
    raw = (cb.data or "")[len(HIDDEN_PREFIX):]
    post = await session.get(Post, int(raw)) if raw.isdigit() else None
    text = options_of(post).get("hidden_text") if post is not None else None
    if not text:
        await cb.answer(t("hidden.gone", locale=lang), show_alert=True)
        return
    chat = cb.message.chat if cb.message is not None else None
    if chat is not None and chat.type != "private":
        try:
            member = await bot.get_chat_member(chat.id, cb.from_user.id)
        except TelegramAPIError as e:
            log.info("membership check in %s failed: %s", chat.id, e)
            member = None
        if not _is_in(member):
            await cb.answer(t("hidden.subscribe", locale=lang), show_alert=True)
            return
    await cb.answer(text, show_alert=True)


async def _boosts(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        return bool((await bot.get_user_chat_boosts(chat_id, user_id)).boosts)
    except TelegramAPIError as e:
        log.info("boost check in %s failed: %s", chat_id, e)
        return False


@router.callback_query(F.data.startswith(HIDDEN_BTN_PREFIX))
async def on_hidden_button(cb: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    """A «Приховане продовження» button: its text for subscribers (or boosters), the outsiders' text for the rest."""
    lang = detect_lang(cb.from_user.language_code)
    post_id, _, hid = (cb.data or "")[len(HIDDEN_BTN_PREFIX):].partition(":")
    post = await session.get(Post, int(post_id)) if post_id.isdigit() else None
    button = find_hidden(post, hid) if post is not None and hid else None
    if button is None:
        await cb.answer(t("hidden.gone", locale=lang), show_alert=True)
        return
    chat = cb.message.chat if cb.message is not None else None
    if chat is not None and chat.type != "private" and not await _may_see(bot, chat.id, cb.from_user.id, button):
        default = "hidden.need_boost" if button.get("audience") == "boost" else "hidden.subscribe"
        await cb.answer(button.get("locked") or t(default, locale=lang), show_alert=True)
        return
    await cb.answer(button["hidden"], show_alert=True)


async def _may_see(bot: Bot, chat_id: int, user_id: int, button: dict) -> bool:
    """A subscriber of the chat — or a booster, for a button meant for boosters."""
    if button.get("audience") == "boost":
        return await _boosts(bot, chat_id, user_id)
    try:
        return _is_in(await bot.get_chat_member(chat_id, user_id))
    except TelegramAPIError as e:
        log.info("membership check in %s failed: %s", chat_id, e)
        return False


@router.callback_query(F.data.startswith(QUIZ_PREFIX))
async def on_quiz_answer(cb: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    """A quiz answer button: the first answer someone taps is theirs; every tap shows that answer's comment and how
    many people answered the same."""
    lang = detect_lang(cb.from_user.language_code)
    post_id, _, hid = (cb.data or "")[len(QUIZ_PREFIX):].partition(":")
    post = await session.get(Post, int(post_id)) if post_id.isdigit() else None
    button = find_hidden(post, hid) if post is not None and hid else None
    if button is None or "quiz" not in button:
        await cb.answer(t("hidden.gone", locale=lang), show_alert=True)
        return
    chat = cb.message.chat if cb.message is not None else None
    if chat is None or chat.type == "private":  # the owner's preview: nothing is counted
        await cb.answer(button["comment"][:MAX_HIDDEN], show_alert=True)
        return
    if not await _may_see(bot, chat.id, cb.from_user.id, button):
        await cb.answer(quiz_locked_text(button, lang)[:MAX_HIDDEN], show_alert=True)
        return
    quiz = button["quiz"]
    vote = await session.scalar(select(QuizVote).where(
        QuizVote.post_id == post.id, QuizVote.quiz == quiz, QuizVote.user_tg_id == cb.from_user.id,
    ))
    if vote is None:
        try:
            async with session.begin_nested():
                vote = QuizVote(post_id=post.id, quiz=quiz, answer=hid, user_tg_id=cb.from_user.id)
                session.add(vote)
        except IntegrityError:  # a double tap: the other one counted it
            vote = await session.scalar(select(QuizVote).where(
                QuizVote.post_id == post.id, QuizVote.quiz == quiz, QuizVote.user_tg_id == cb.from_user.id,
            ))
    mine = next((b for b in quiz_answers(post, quiz) if b["hid"] == vote.answer), button)
    counts = dict((await session.execute(
        select(QuizVote.answer, func.count()).where(QuizVote.post_id == post.id, QuizVote.quiz == quiz)
        .group_by(QuizVote.answer)
    )).all())
    total, same = sum(counts.values()), counts.get(mine["hid"], 0)
    pct = round(same * 100 / total) if total else 0
    head = t("qz.yours", text=mine["text"], locale=lang) + "\n\n" if mine["hid"] != hid else ""
    stats = t("qz.stats", pct=pct, n=same, total=total, locale=lang)
    if len(head) + len(mine["comment"]) + len(stats) + 2 > MAX_HIDDEN:
        stats = t("qz.stats_short", pct=pct, locale=lang)
    room = MAX_HIDDEN - len(head) - len(stats) - 2
    comment = mine["comment"] if len(mine["comment"]) <= room else mine["comment"][:room - 1] + "…"
    await cb.answer(f"{head}{comment}\n\n{stats}", show_alert=True)


@router.callback_query(F.data.startswith(GIVEAWAY_PREFIX))
async def on_giveaway_tap(cb: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    lang = detect_lang(cb.from_user.language_code)
    raw = (cb.data or "")[len(GIVEAWAY_PREFIX):]
    status = (await giveaway.join(bot, session, int(raw), cb.from_user))[0] if raw.isdigit() else "gone"
    await cb.answer(t(f"gwb.app_{status}", locale=lang), show_alert=True)
