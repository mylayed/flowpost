"""Background worker: due publications, auto-repeat, auto-delete, unpin, reminders, join requests, RSS sources,
subscriber counts and weekly reports."""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import date, datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramMigrateToChat,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyParameters, WebAppInfo
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flowpost.bot.callbacks import Cp, Cs, Px
from flowpost.bot.keyboards.common import btn, markup, pay_btn
from flowpost.config import Settings
from flowpost.db.models import Broadcast, Channel, Commenter, Feed, JoinRequest, MemberCount, Post, Publication, Subscription, User
from flowpost.db.repo import channel_admins as channel_admins_repo
from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import posts as posts_repo
from flowpost.db.repo import publications as pubs_repo
from flowpost.db.repo.publications import refresh_post_status
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services import ads, ai_moderation, analytics, broadcast, gaps, giveaway, growth, pro_ai, rss
from flowpost.services.ai import AIError, AIService
from flowpost.services.billing import limits
from flowpost.services.billing import entitlements
from flowpost.services.delivery import (
    DeliveryError,
    DeliveryOutcome,
    delete_publication_messages,
    deliver_publication,
    publication_message_ids,
)
from flowpost.services.html_sanitize import visible_len
from flowpost.services.moderation import moderation_settings
from flowpost.services.posts import TEXT_LIMIT, channel_defaults, initial_options, render_signature
from flowpost.services.publisher import EmptyPostError, Publisher
from flowpost.services.reports import report_due_since, weekly_report
from flowpost.services.slots import day_bounds_utc, tz_of

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BATCH = 20
FEEDS_PER_TICK = 5
MEMBERS_EVERY = timedelta(hours=1)
REPORTS_EVERY = timedelta(minutes=10)
GAPS_EVERY = timedelta(minutes=10)


def next_day_same_time(run_at: datetime, tz_name: str, now: datetime) -> datetime:
    """The publication's local time of day, on the owner's next calendar day."""
    tz = tz_of(tz_name)
    day = now.astimezone(tz).date() + timedelta(days=1)
    return datetime.combine(day, run_at.astimezone(tz).time(), tzinfo=tz).astimezone(timezone.utc)


class Worker:
    def __init__(
        self, bot: Bot, sessionmaker: async_sessionmaker, publisher: Publisher, settings: Settings,
        ai: AIService | None = None,
    ):
        self.bot = bot
        self.sessionmaker = sessionmaker
        self.publisher = publisher
        self.settings = settings
        self.ai = ai
        self._wake = asyncio.Event()
        self._members_at: datetime | None = None
        self._reports_at: datetime | None = None
        self._gaps_at: datetime | None = None
        self._gaps_checked: dict[int, date] = {}  # channel id -> the owner's local day it was last checked
        self._broadcasts: dict[int, asyncio.Task] = {}  # broadcasts being sent by this process
        self.ai_moderation = ai_moderation.Queue(settings.ai_mod_batch, settings.ai_mod_wait_seconds)
        self.questions: list[pro_ai.Question] = []  # comments waiting for the AI answerer

    def wake(self) -> None:
        self._wake.set()

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep the loop alive
                log.exception("worker tick failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.settings.worker_interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def tick(self, now: datetime | None = None) -> None:
        now = now or utcnow()
        await self.recover_stale()
        await self.process_due(now)
        await self.process_broadcasts(now)
        await self.process_unpins(now)
        await self.process_deletes(now)
        await self.trial_reminders(now)
        await self.subscription_reminders(now)
        await self.process_join_approvals(now)
        await self.giveaway_counters()
        await self.poll_feeds(now)
        await self.snapshot_members(now)
        await self.weekly_reports(now)
        await self.gap_reminders(now)
        await self.process_ai_moderation()
        await self.process_questions()

    async def recover_stale(self) -> None:
        """Publications stuck in 'publishing' after a crash are marked failed instead of risking duplicates."""
        cutoff = utcnow() - timedelta(minutes=15)
        async with self.sessionmaker() as session:
            rows = (await session.scalars(
                select(Publication).where(Publication.status == "publishing", Publication.run_at < cutoff)
            )).all()
            for pub in rows:
                pub.status = "failed"
                pub.last_error = "interrupted"
            await session.commit()

    # ---- broadcasts --------------------------------------------------------------------------

    async def process_broadcasts(self, now: datetime) -> None:
        """Start the owner's broadcasts that are due, and pick up ones a restart cut off. Each runs as its own task,
        so a long broadcast doesn't hold up publishing."""
        async with self.sessionmaker() as session:
            due = (await session.scalars(
                select(Broadcast).where(Broadcast.status == "pending", Broadcast.send_at <= now)
            )).all()
            for bc in due:
                bc.status = "sending"
            await session.commit()
            ids = (await session.scalars(select(Broadcast.id).where(Broadcast.status == "sending"))).all()
        for bc_id in ids:
            if bc_id not in self._broadcasts:
                task = asyncio.create_task(broadcast.run(self.bot, self.sessionmaker, self.settings, bc_id))
                self._broadcasts[bc_id] = task
                task.add_done_callback(lambda done, bc_id=bc_id: self._broadcast_done(bc_id, done))

    def _broadcast_done(self, bc_id: int, task: asyncio.Task) -> None:
        self._broadcasts.pop(bc_id, None)
        if not task.cancelled() and task.exception() is not None:
            log.error("broadcast %s failed", bc_id, exc_info=task.exception())

    async def wait_broadcasts(self) -> None:
        """For tests: let the running broadcasts finish."""
        while self._broadcasts:
            await asyncio.gather(*self._broadcasts.values(), return_exceptions=True)

    # ---- publishing -------------------------------------------------------------------------

    async def process_due(self, now: datetime) -> None:
        async with self.sessionmaker() as session:
            rows = (await session.scalars(
                select(Publication)
                .where(Publication.status == "pending", Publication.run_at <= now)
                .order_by(Publication.run_at)
                .limit(BATCH)
                .with_for_update(skip_locked=True)
            )).all()
            for pub in rows:
                pub.status = "publishing"
                pub.attempts += 1
            ids = [p.id for p in rows]
            await session.commit()
        paywalled: set[int] = set()
        for pub_id in ids:
            await self.deliver(pub_id, now, paywalled=paywalled)

    async def deliver(self, pub_id: int, now: datetime | None = None, *, paywalled: set[int] | None = None) -> DeliveryOutcome:
        """Deliver one claimed publication (status 'publishing') and notify the owner if needed."""
        now = now or utcnow()
        async with self.sessionmaker() as session:
            pub = await session.get(Publication, pub_id)
            if pub is None:
                return DeliveryOutcome(ok=False, error="err.pub_missing")
            owner = await session.get(User, pub.owner_id)
            channel = await session.get(Channel, pub.channel_id)
            post = await session.get(Post, pub.post_id)
            title = channel.title if channel else ""
            outcome: DeliveryOutcome
            notify_key: str | None = None

            entitlement = (
                await entitlements.for_channel(session, self.settings, channel, owner, now)
                if owner is not None and channel is not None
                else None
            )
            if post is not None and ads.is_booking(post):
                # A booked ad slot nobody confirmed in time: the slot is given up.
                pub.status = "cancelled"
                outcome = DeliveryOutcome(ok=False, channel_title=title, error="err.booking_unconfirmed")
                notify_key = "notify.booking_unconfirmed"
            elif entitlement is None or entitlement.plan == "none":
                pub.status = "paused"
                outcome = DeliveryOutcome(ok=False, channel_title=title, error="err.no_access")
                if owner and pub.notify and (paywalled is None or owner.id not in paywalled):
                    notify_key = "notify.paused"
                    if paywalled is not None:
                        paywalled.add(owner.id)
            elif not entitlements.has_extras(entitlement) and post is not None and (
                pub.repeat_index > 0 or len(post.targets) > 1
            ):
                # Auto-repeat and multiposting aren't on the free plan; paying for the channel resumes them.
                pub.status = "paused"
                outcome = DeliveryOutcome(ok=False, channel_title=title, error="err.extras_plan")
                if owner and pub.notify and (paywalled is None or owner.id not in paywalled):
                    notify_key = "notify.paused_extras"
                    if paywalled is not None:
                        paywalled.add(owner.id)
            elif now - pub.run_at > timedelta(hours=self.settings.missed_grace_hours):
                pub.status = "missed"
                outcome = DeliveryOutcome(ok=False, channel_title=title, error="err.missed")
                notify_key = "notify.missed" if pub.notify else None
            elif (
                post is not None and not post.is_ad
                and (top_end := await ads.top_until(session, pub.channel_id, now)) is not None
            ):
                # An ad is in its «top» hours: everything else in the channel waits until they're over.
                pub.status = "pending"
                pub.attempts = max(0, pub.attempts - 1)
                pub.run_at = top_end
                local_run = top_end.astimezone(tz_of(owner.tz))
                outcome = DeliveryOutcome(
                    ok=False, channel_title=title, error="err.ad_top", detail=local_run.strftime("%d.%m %H:%M")
                )
            elif await entitlements.posts_left(session, self.settings, channel, owner, entitlement, now) == 0:
                pub.status = "pending"
                pub.attempts = 0
                pub.run_at = next_day_same_time(pub.run_at, owner.tz, now)
                local_run = pub.run_at.astimezone(tz_of(owner.tz))
                outcome = DeliveryOutcome(
                    ok=False, channel_title=title, error="err.post_limit", detail=local_run.strftime("%d.%m %H:%M")
                )
                if pub.notify and await self._limit_notice_due(session, owner, now):
                    notify_key = "notify.limit"
            else:
                try:
                    outcome = await deliver_publication(
                        session, self.publisher, pub, now=now, extras=entitlements.has_extras(entitlement), ai=self.ai,
                    )
                    notify_key = "notify.published" if pub.notify and channel is not None and channel.notify_published else None
                except TelegramRetryAfter as e:
                    pub.status = "pending"
                    pub.run_at = now + timedelta(seconds=e.retry_after + 1)
                    outcome = DeliveryOutcome(ok=False, channel_title=title, error="err.retry_later")
                except TelegramMigrateToChat as e:
                    # The group is a supergroup now. Nothing was sent, so once its id is fixed the next tick
                    # publishes it, without this attempt counting against the post.
                    await channels_repo.migrate_chat(session, channel.chat_id, e.migrate_to_chat_id)
                    pub.status = "pending"
                    pub.attempts = max(0, pub.attempts - 1)
                    pub.run_at = now
                    outcome = DeliveryOutcome(ok=False, channel_title=title, error="err.retry_later")
                    self.wake()
                except (TelegramNetworkError, TelegramServerError) as e:
                    outcome = self._retry_or_fail(pub, now, str(e), title)
                    notify_key = "notify.failed" if pub.status == "failed" and pub.notify else None
                except TelegramForbiddenError as e:
                    if channel is not None:
                        channel.is_active = False
                    outcome = self._fail(pub, "err.bot_not_admin", str(e), title)
                    notify_key = "notify.failed" if pub.notify else None
                except TelegramBadRequest as e:
                    outcome = self._fail(pub, "err.telegram", str(e), title)
                    notify_key = "notify.failed" if pub.notify else None
                except (DeliveryError, EmptyPostError) as e:
                    key = e.key if isinstance(e, DeliveryError) else "err.post_empty"
                    outcome = self._fail(pub, key, key, title)
                    notify_key = "notify.failed" if pub.notify else None
                except Exception as e:  # noqa: BLE001
                    log.exception("unexpected delivery error for pub %s", pub_id)
                    outcome = self._retry_or_fail(pub, now, repr(e), title)
                    notify_key = "notify.failed" if pub.status == "failed" and pub.notify else None
            if post is not None:
                await refresh_post_status(session, post)
            await session.commit()

        if notify_key == "notify.published" and owner is not None and channel is not None:
            await self._notify_published(channel, owner, outcome)
        elif notify_key and owner is not None and not owner.is_blocked:
            await self._notify(owner, notify_key, outcome)
        return outcome

    @staticmethod
    def _fail(pub: Publication, key: str, detail: str, title: str) -> DeliveryOutcome:
        pub.status = "failed"
        pub.last_error = detail[:1000]
        return DeliveryOutcome(ok=False, channel_title=title, error=key, detail=detail[:200])

    def _retry_or_fail(self, pub: Publication, now: datetime, detail: str, title: str) -> DeliveryOutcome:
        if pub.attempts < MAX_ATTEMPTS:
            pub.status = "pending"
            pub.run_at = now + timedelta(minutes=pub.attempts)
            pub.last_error = detail[:1000]
            return DeliveryOutcome(ok=False, channel_title=title, error="err.retry_later")
        return self._fail(pub, "err.network", detail, title)

    @staticmethod
    async def _limit_notice_due(session, owner: User, now: datetime) -> bool:
        """At most one «post limit reached» message per owner per local day."""
        day_start, _ = day_bounds_utc(now.astimezone(tz_of(owner.tz)).date(), owner.tz)
        if await analytics.count_since(session, owner.id, "post_limit_notice", day_start):
            return False
        analytics.track(session, owner.id, "post_limit_notice")
        return True

    @staticmethod
    def _notify_text(key: str, lang: str, outcome: DeliveryOutcome) -> str:
        error_text = t(outcome.error or "err.unknown", locale=lang)
        if outcome.detail:
            error_text += f" — {html.escape(outcome.detail)}"
        params = {
            "title": html.escape(outcome.channel_title),
            "link": outcome.link or "",
            "error": error_text,
        }
        text = t(key, locale=lang, **params)
        for w in outcome.warnings:
            text += "\n⚠️ " + t(w, locale=lang)
        return text

    async def _mark_blocked(self, owner: User) -> None:
        async with self.sessionmaker() as session:
            db_owner = await session.get(User, owner.id)
            if db_owner:
                db_owner.is_blocked = True
                await session.commit()

    async def _notify(self, owner: User, key: str, outcome: DeliveryOutcome) -> None:
        markup = None
        if key in ("notify.paused", "notify.paused_extras", "notify.limit"):
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                pay_btn(self.settings, t("btn.pay", locale=owner.lang))
            ]])
        text = self._notify_text(key, owner.lang, outcome)
        try:
            await self.bot.send_message(owner.tg_id, text, reply_markup=markup)
        except TelegramForbiddenError:
            await self._mark_blocked(owner)
        except TelegramAPIError as e:
            log.warning("notify failed: %s", e)

    async def _resolve_publish_recipients(self, channel: Channel, owner: User) -> list[int]:
        """Telegram user ids to notify about a publish, per the channel's notify_recipients setting."""
        recipients = channel.notify_recipients or "owner"
        ids: list[int] = []
        if recipients in ("owner", "both") and not owner.is_blocked:
            ids.append(owner.tg_id)
        if recipients in ("admin", "both"):
            try:
                admins = await self.bot.get_chat_administrators(channel.chat_id)
            except TelegramAPIError as e:
                log.info("could not fetch admins for channel %s: %s", channel.id, e)
                admins = []
            for admin in admins:
                if not admin.user.is_bot and admin.user.id not in ids:
                    ids.append(admin.user.id)
        return ids

    async def _notify_published(self, channel: Channel, owner: User, outcome: DeliveryOutcome) -> None:
        recipients = await self._resolve_publish_recipients(channel, owner)
        if not recipients:
            return
        text = self._notify_text("notify.published", owner.lang, outcome)
        for tg_id in recipients:
            try:
                await self.bot.send_message(tg_id, text)
            except TelegramForbiddenError:
                if tg_id == owner.tg_id:
                    await self._mark_blocked(owner)
            except TelegramAPIError as e:
                log.warning("published notify failed for %s: %s", tg_id, e)

    # ---- maintenance ------------------------------------------------------------------------

    async def process_deletes(self, now: datetime) -> None:
        async with self.sessionmaker() as session:
            rows = (await session.scalars(
                select(Publication)
                .where(Publication.delete_at.is_not(None), Publication.delete_at <= now, Publication.deleted.is_(False))
                .limit(BATCH)
            )).all()
            for pub in rows:
                channel = await session.get(Channel, pub.channel_id)
                if channel is not None:
                    await delete_publication_messages(self.bot, channel, pub)
                else:
                    pub.deleted = True
                    pub.delete_at = None
            await session.commit()

    async def process_unpins(self, now: datetime) -> None:
        async with self.sessionmaker() as session:
            rows = (await session.scalars(
                select(Publication)
                .where(Publication.unpin_at.is_not(None), Publication.unpin_at <= now)
                .limit(BATCH)
            )).all()
            for pub in rows:
                channel = await session.get(Channel, pub.channel_id)
                ids = publication_message_ids(pub)
                if channel is not None and ids and not pub.deleted:
                    try:
                        await self.bot.unpin_chat_message(channel.chat_id, message_id=ids[0])
                    except TelegramAPIError as e:
                        log.warning("unpin failed for pub %s: %s", pub.id, e)
                pub.unpin_at = None
            await session.commit()

    async def trial_reminders(self, now: datetime) -> None:
        """Trials are per channel (they start when it's connected), so each channel's owner is reminded on its own."""
        async with self.sessionmaker() as session:
            rows = (await session.execute(
                select(Channel, User)
                .join(User, User.id == Channel.owner_id)
                .where(
                    Channel.trial_reminded.is_(False),
                    Channel.is_active.is_(True),
                    Channel.trial_ends_at > now,
                    Channel.trial_ends_at <= now + timedelta(days=1),
                    User.is_blocked.is_(False),
                )
                .limit(BATCH)
            )).all()
            to_notify = []
            for channel, user in rows:
                channel.trial_reminded = True
                entitlement = await entitlements.for_channel(session, self.settings, channel, user, now)
                if entitlement.plan == "trial":  # a paid plan bought during the trial needs no reminder
                    to_notify.append((user.tg_id, user.lang, channel.title))
            await session.commit()
        for tg_id, lang, title in to_notify:
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                pay_btn(self.settings, t("btn.pay", locale=lang))
            ]])
            try:
                await self.bot.send_message(
                    tg_id, t("notify.trial_ending", locale=lang, title=html.escape(title)), reply_markup=markup
                )
            except TelegramAPIError as e:
                log.info("trial reminder not delivered: %s", e)

    async def subscription_reminders(self, now: datetime) -> None:
        async with self.sessionmaker() as session:
            rows = (await session.execute(
                select(Subscription, User)
                .join(User, User.id == Subscription.user_id)
                .where(
                    Subscription.status.in_(("active", "cancelled")),
                    Subscription.renewal_reminded.is_(False),
                    Subscription.current_period_end > now,
                    Subscription.current_period_end <= now + timedelta(days=1),
                    User.is_blocked.is_(False),
                )
                .limit(BATCH)
            )).all()
            to_notify = []
            for sub, user in rows:
                sub.renewal_reminded = True
                to_notify.append((user.tg_id, user.lang))
            await session.commit()
        for tg_id, lang in to_notify:
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                pay_btn(self.settings, t("btn.pay", locale=lang))
            ]])
            try:
                await self.bot.send_message(tg_id, t("notify.sub_ending", locale=lang), reply_markup=markup)
            except TelegramAPIError as e:
                log.info("subscription reminder not delivered: %s", e)

    # ---- PRO tools --------------------------------------------------------------------------

    async def _has_extras(self, session: AsyncSession, channel: Channel, now: datetime) -> User | None:
        """The channel's owner if the channel is on a paid plan or trial (PRO tools only work then), else None."""
        owner = await session.get(User, channel.owner_id)
        if owner is None:
            return None
        entitlement = await entitlements.for_channel(session, self.settings, channel, owner, now)
        return owner if entitlements.has_extras(entitlement) else None

    async def process_ai_moderation(self, *, flush: bool = False) -> None:
        """Check the comments waiting in the AI moderation queue; `flush` sends every batch without waiting."""
        if self.ai is None or not self.ai.enabled:
            return
        for channel_id, items in self.ai_moderation.due(flush=flush):
            try:
                await self._moderate_batch(channel_id, items)
            except Exception:  # noqa: BLE001 - one channel's batch mustn't stop the others
                log.exception("AI moderation failed for channel %s", channel_id)

    async def _moderate_batch(self, channel_id: int, items: list[ai_moderation.Pending]) -> None:
        now = utcnow()
        notify: tuple[int, str, str] | None = None
        async with self.sessionmaker() as session:
            channel = await session.get(Channel, channel_id)
            mod = moderation_settings(channel.moderation if channel else None)
            if channel is None or not channel.is_active or not (mod["enabled"] and mod["ai"]):
                return
            owner = await self._has_extras(session, channel, now)
            if owner is None:
                return
            paused = not await limits.take(session, channel.id, "ai_mod")
            if paused and not mod["ai_out"]:
                channel.moderation = {**mod, "ai_out": True}
                notify = (owner.tg_id, owner.lang, channel.title)
            elif not paused and mod["ai_out"]:
                channel.moderation = {**mod, "ai_out": False}
            title = channel.title
            await session.commit()
        if paused:
            # Out of checks: the word/link filters keep working; the owner hears about it once until they top up.
            if notify is None:
                return
            tg_id, lang, title = notify
            kb = markup([[pay_btn(self.settings, t("aimod.buy_btn", locale=lang))]])
            try:
                await self.bot.send_message(tg_id, t("aimod.out", locale=lang, title=html.escape(title)), reply_markup=kb)
            except TelegramAPIError as e:
                log.info("AI moderation pause notice not delivered: %s", e)
            return
        try:
            verdicts = await self.ai.moderate([item.text for item in items], channel_title=title)  # type: ignore[union-attr]
        except AIError as e:
            log.info("AI moderation for channel %s failed: %s", channel_id, e.key)
            async with self.sessionmaker() as session:
                await limits.add(session, channel_id, "ai_mod", 1)
                await session.commit()
            return
        deleted: list[ai_moderation.Pending] = []
        for item, verdict in zip(items, verdicts):
            if verdict == "ok":
                continue
            try:
                await self.bot.delete_message(item.chat_id, item.message_id)
                deleted.append(item)
                log.info("AI moderation deleted a %s comment in chat %s", verdict, item.chat_id)
            except TelegramAPIError as e:
                log.info("AI moderation delete failed in chat %s: %s", item.chat_id, e)
        if not deleted:
            return
        async with self.sessionmaker() as session:
            for item in deleted:
                pub = await session.get(Publication, item.publication_id) if item.publication_id else None
                if pub is None:
                    continue
                pub.comments_count = max((pub.comments_count or 0) - 1, 0)
                await session.execute(
                    delete(Commenter).where(Commenter.publication_id == pub.id, Commenter.user_tg_id == item.user_tg_id)
                )
            await session.commit()

    MAX_QUESTIONS = 500  # a runaway flood can't grow memory without bound; the extra comments go unanswered

    def add_question(self, question: pro_ai.Question) -> None:
        if len(self.questions) < self.MAX_QUESTIONS:
            self.questions.append(question)
            self.wake()

    async def process_questions(self) -> None:
        """Let the AI answerer reply to the questions in comments, or pass the ones it can't answer to the team."""
        if self.ai is None or not self.ai.enabled:
            self.questions.clear()
            return
        while self.questions:
            question = self.questions.pop(0)
            try:
                await self._answer_question(question)
            except Exception:  # noqa: BLE001 - one comment mustn't stop the others
                log.exception("AI answerer failed for channel %s", question.channel_id)

    async def _answer_question(self, q: pro_ai.Question) -> None:
        now = utcnow()
        notify_out: tuple[int, str, str] | None = None
        async with self.sessionmaker() as session:
            channel = await session.get(Channel, q.channel_id)
            s = pro_ai.tools_settings(channel.ai_tools if channel else None)
            if channel is None or not channel.is_active or not s["answer"] or not s["kb"].strip():
                return
            owner = await self._has_extras(session, channel, now)
            if owner is None:
                return
            paused = not await limits.take(session, channel.id, "ai_text")
            if paused != s["answer_out"]:
                channel.ai_tools = {**s, "answer_out": paused}
                if paused:
                    notify_out = (owner.tg_id, owner.lang, channel.title)
            pub = await session.get(Publication, q.publication_id) if q.publication_id else None
            post = await session.get(Post, pub.post_id) if pub else None
            post_text = "\n\n".join(p.text_html for p in post.parts if p.text_html) if post else ""
            title, kb = channel.title, s["kb"]
            recipients = [(owner.tg_id, owner.lang)] + [
                (user.tg_id, user.lang) for admin, user in await channel_admins_repo.list_admins(session, channel.id)
                if admin.can_posts or admin.can_settings
            ]
            await session.commit()
        if paused:
            # Out of AI texts: the owner hears about it once until they top up.
            if notify_out is not None:
                tg_id, lang, name = notify_out
                kb_pay = markup([[pay_btn(self.settings, t("aians.buy_btn", locale=lang))]])
                try:
                    await self.bot.send_message(tg_id, t("aians.out", locale=lang, title=html.escape(name)), reply_markup=kb_pay)
                except TelegramAPIError as e:
                    log.info("AI answerer pause notice not delivered: %s", e)
            return
        try:
            action, reply = await self.ai.answer_comment(  # type: ignore[union-attr]
                q.text, knowledge=kb, post=post_text, channel_title=title,
            )
        except AIError as e:
            log.info("AI answerer for channel %s failed: %s", q.channel_id, e.key)
            async with self.sessionmaker() as session:
                await limits.add(session, q.channel_id, "ai_text", 1)
                await session.commit()
            return
        if action == "answer":
            try:
                await self.bot.send_message(
                    q.chat_id, html.escape(reply), message_thread_id=q.thread_id,
                    reply_parameters=ReplyParameters(message_id=q.message_id, allow_sending_without_reply=True),
                )
            except TelegramAPIError as e:
                log.info("AI answerer reply failed in chat %s: %s", q.chat_id, e)
        elif action == "escalate":
            link = pro_ai.comment_link(q.chat_id, q.message_id, q.thread_id)
            for tg_id, lang in dict(recipients).items():
                rows = [[InlineKeyboardButton(text=t("aians.open_btn", locale=lang), url=link)]] if link else []
                text = t("aians.escalated", locale=lang, title=html.escape(title), text=html.escape(q.text[:1000]))
                try:
                    await self.bot.send_message(tg_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None)
                except TelegramAPIError as e:
                    log.info("AI answerer escalation not delivered to %s: %s", tg_id, e)

    async def process_join_approvals(self, now: datetime) -> None:
        async with self.sessionmaker() as session:
            rows = (await session.scalars(
                select(JoinRequest)
                .where(JoinRequest.approve_at.is_not(None), JoinRequest.approve_at <= now, JoinRequest.approved_at.is_(None))
                .limit(BATCH)
            )).all()
            for row in rows:
                channel = await session.get(Channel, row.channel_id)
                if channel is None or not channel.is_active:
                    row.approve_at = None  # left for the channel's admins to handle by hand
                    continue
                await growth.approve_request(self.bot, session, channel, row, now)
            await session.commit()

    async def giveaway_counters(self) -> None:
        async with self.sessionmaker() as session:
            await giveaway.refresh_counters(self.bot, session)
            await session.commit()

    async def poll_feeds(self, now: datetime) -> None:
        due_before = now - timedelta(minutes=self.settings.rss_interval_minutes)
        async with self.sessionmaker() as session:
            feed_ids = list((await session.scalars(
                select(Feed.id)
                .join(Channel, Channel.id == Feed.channel_id)
                .where(Feed.active.is_(True), Channel.is_active.is_(True),
                       or_(Feed.checked_at.is_(None), Feed.checked_at < due_before))
                .order_by(Feed.checked_at.nulls_first())
                .limit(FEEDS_PER_TICK)
            )).all())
        for feed_id in feed_ids:
            try:
                await self.poll_feed(feed_id, now)
            except Exception:  # noqa: BLE001 - one broken source mustn't stop the others
                log.exception("feed %s failed", feed_id)

    async def poll_feed(self, feed_id: int, now: datetime) -> None:
        drafts: list[tuple[Post, str]] = []
        async with self.sessionmaker() as session:
            feed = await session.get(Feed, feed_id)
            channel = await session.get(Channel, feed.channel_id) if feed is not None else None
            if feed is None or channel is None:
                return
            feed.checked_at = now
            owner = await self._has_extras(session, channel, now)
            if owner is None:
                feed.last_error = "rss.err_plan"
                await session.commit()
                return
            try:
                parsed = rss.parse(await rss.fetch(feed.url))
            except rss.FeedError as e:
                feed.last_error = e.key
                await session.commit()
                return
            feed.last_error = None
            fresh, feed.seen = rss.new_items(list(feed.seen or []), parsed.items, self.settings.rss_items_per_check)
            for item in fresh:
                text = await self._feed_text(session, channel, owner, feed, item)
                post = await posts_repo.create_post(
                    session, owner.id, [channel.id], options=initial_options(channel, False), text=text,
                    buttons=channel_defaults(channel)["buttons"],
                )
                if feed.mode == "auto":
                    await pubs_repo.create_publications(session, post, now)
                    await refresh_post_status(session, post)
                else:
                    drafts.append((post, text))
            await session.commit()
            title, owner_tg, lang, blocked = feed.title or feed.url, owner.tg_id, owner.lang, owner.is_blocked
        if fresh and feed.mode == "auto":
            self.wake()
        for post, text in drafts if not blocked else []:
            header = t("rss.draft_title", locale=lang, feed=html.escape(title))
            body = f"{header}\n\n{text}" if visible_len(text) + len(header) < 3900 else text
            kb = markup([
                [btn(t("rss.draft_publish", locale=lang), Px(a="rss_pub", id=post.id)),
                 btn(t("rss.draft_edit", locale=lang), Px(a="rss_edit", id=post.id))],
                [btn(t("rss.draft_skip", locale=lang), Px(a="rss_skip", id=post.id))],
            ])
            try:
                await self.bot.send_message(owner_tg, body, reply_markup=kb)
            except TelegramAPIError as e:
                log.info("RSS draft for %s not delivered: %s", owner_tg, e)

    async def _feed_text(self, session: AsyncSession, channel: Channel, owner: User, feed: Feed, item: rss.FeedItem) -> str:
        """The item rewritten by AI in the channel's style when the source asks for it and the channel has AI texts
        left; otherwise title, summary and link as they are."""
        plain = rss.item_post(item, t("rss.read_more", locale=owner.lang))
        if not feed.rewrite or self.ai is None or not self.ai.enabled:
            return plain
        if not await limits.take(session, channel.id, "ai_text"):
            return plain
        limit = TEXT_LIMIT - (visible_len(render_signature(channel)) + 2 if channel.signature_on else 0)
        try:
            text = await self.ai.generate(
                "rss", text=rss.item_source(item), lang=owner.lang, limit=max(500, limit),
                style=channel.ai_style_prompt,
            )
        except AIError:
            await limits.add(session, channel.id, "ai_text", 1)
            return plain
        analytics.track(session, owner.id, "ai_call", action="rss")
        return text

    async def snapshot_members(self, now: datetime) -> None:
        """Once a day per channel: its subscriber count, for the weekly report's growth line."""
        if self._members_at is not None and now - self._members_at < MEMBERS_EVERY:
            return
        self._members_at = now
        today = now.date()
        async with self.sessionmaker() as session:
            channels = (await session.scalars(
                select(Channel)
                .where(Channel.is_active.is_(True), Channel.weekly_report.is_(True),
                       Channel.id.not_in(select(MemberCount.channel_id).where(MemberCount.day == today)))
                .limit(100)
            )).all()
            for channel in channels:
                try:
                    count = await self.bot.get_chat_member_count(channel.chat_id)
                except TelegramMigrateToChat as e:
                    await channels_repo.migrate_chat(session, channel.chat_id, e.migrate_to_chat_id)
                    continue  # counted from the new id on the next pass
                except TelegramAPIError as e:
                    log.info("member count of %s unavailable: %s", channel.chat_id, e)
                    continue
                session.add(MemberCount(channel_id=channel.id, day=today, count=count))
            await session.commit()

    async def gap_reminders(self, now: datetime) -> None:
        """Tell the owner and the posting admins that tomorrow has nothing scheduled (see services.gaps).

        Each opted-in channel is looked at once a day, after 10:00 in its owner's zone; the answer for the day is kept
        in memory so the ten-minute ticks don't repeat the queries (a restart just checks again)."""
        if self._gaps_at is not None and now - self._gaps_at < GAPS_EVERY:
            return
        self._gaps_at = now
        outbox: list[tuple[User, Channel, str, bool]] = []
        async with self.sessionmaker() as session:
            rows = (await session.execute(
                select(Channel, User)
                .join(User, User.id == Channel.owner_id)
                .where(
                    Channel.is_active.is_(True), Channel.gap_reminder.is_(True), User.is_blocked.is_(False),
                    Channel.created_at < now - timedelta(days=1),
                )
            )).tuples().all()
            for channel, owner in rows:
                today = gaps.check_day(owner, now)
                if today is None or self._gaps_checked.get(channel.id) == today:
                    continue
                self._gaps_checked[channel.id] = today
                if not gaps.due_again(channel, today):
                    continue
                entitlement = await entitlements.for_channel(session, self.settings, channel, owner, now)
                if entitlement.plan == "none" or await gaps.is_dormant(session, channel, now):
                    continue
                empty = await gaps.empty_days(session, channel, owner, today)
                if today + timedelta(days=1) not in empty:
                    continue
                channel.gap_reminded_on = today
                for recipient, can_mute in await gaps.recipients(session, channel, owner):
                    text = await gaps.reminder_text(session, channel, recipient, empty, today)
                    outbox.append((recipient, channel, text, can_mute))
            await session.commit()
        for recipient, channel, text, can_mute in outbox:
            url = self.settings.calendar_url(channel.id)
            label = t("gap.calendar_btn", locale=recipient.lang)
            open_btn = (InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url)) if url
                        else btn(t("gap.plan_btn", locale=recipient.lang), Cp(a="day", c=channel.id)))
            rows = [[open_btn]]
            if can_mute:
                rows.append([btn(t("gap.off_btn", locale=recipient.lang), Cs(a="gap_off", c=channel.id))])
            try:
                await self.bot.send_message(recipient.tg_id, text, reply_markup=markup(rows))
            except TelegramForbiddenError:
                await self._mark_blocked(recipient)
            except TelegramAPIError as e:
                log.info("gap reminder for %s not delivered: %s", recipient.tg_id, e)

    async def weekly_reports(self, now: datetime) -> None:
        if self._reports_at is not None and now - self._reports_at < REPORTS_EVERY:
            return
        self._reports_at = now
        outbox: list[tuple[User, int, str]] = []
        async with self.sessionmaker() as session:
            rows = (await session.execute(
                select(Channel, User)
                .join(User, User.id == Channel.owner_id)
                .where(
                    Channel.is_active.is_(True), Channel.weekly_report.is_(True), User.is_blocked.is_(False),
                    Channel.created_at < now - timedelta(days=3),
                    or_(Channel.report_sent_at.is_(None), Channel.report_sent_at < now - timedelta(days=6)),
                )
            )).tuples().all()
            for channel, owner in rows:
                due = report_due_since(owner, now)
                if due is None or (channel.report_sent_at is not None and channel.report_sent_at >= due):
                    continue
                if await self._has_extras(session, channel, now) is None:
                    continue
                outbox.append((owner, channel.id, await weekly_report(session, channel, owner, now)))
                channel.report_sent_at = now
            await session.commit()
        for owner, channel_id, text in outbox:
            kb = markup([[btn(t("wr.off_btn", locale=owner.lang), Px(a="rep_off", c=channel_id))]])
            try:
                await self.bot.send_message(owner.tg_id, text, reply_markup=kb, disable_web_page_preview=True)
            except TelegramForbiddenError:
                await self._mark_blocked(owner)
            except TelegramAPIError as e:
                log.info("weekly report for %s not delivered: %s", owner.tg_id, e)
