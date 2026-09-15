"""Background worker: due publications, auto-repeat, auto-delete, unpin and trial reminders."""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from flowpost.bot.callbacks import Bl
from flowpost.config import Settings
from flowpost.db.models import Channel, Post, Publication, Subscription, User
from flowpost.db.repo.publications import refresh_post_status
from flowpost.db.types import utcnow
from flowpost.i18n import t
from flowpost.services.billing.subscriptions import get_access
from flowpost.services.delivery import (
    DeliveryError,
    DeliveryOutcome,
    delete_publication_messages,
    deliver_publication,
    publication_message_ids,
)
from flowpost.services.publisher import EmptyPostError, Publisher

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BATCH = 20


class Worker:
    def __init__(self, bot: Bot, sessionmaker: async_sessionmaker, publisher: Publisher, settings: Settings):
        self.bot = bot
        self.sessionmaker = sessionmaker
        self.publisher = publisher
        self.settings = settings
        self._wake = asyncio.Event()

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
        await self.process_unpins(now)
        await self.process_deletes(now)
        await self.trial_reminders(now)
        await self.subscription_reminders(now)

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

            access = await get_access(session, owner, now) if owner else None
            if access is None or not access.active:
                pub.status = "paused"
                outcome = DeliveryOutcome(ok=False, channel_title=title, error="err.no_access")
                if owner and pub.notify and (paywalled is None or owner.id not in paywalled):
                    notify_key = "notify.paused"
                    if paywalled is not None:
                        paywalled.add(owner.id)
            elif now - pub.run_at > timedelta(hours=self.settings.missed_grace_hours):
                pub.status = "missed"
                outcome = DeliveryOutcome(ok=False, channel_title=title, error="err.missed")
                notify_key = "notify.missed" if pub.notify else None
            else:
                try:
                    outcome = await deliver_publication(session, self.publisher, pub, now=now)
                    notify_key = "notify.published" if pub.notify and channel is not None and channel.notify_published else None
                except TelegramRetryAfter as e:
                    pub.status = "pending"
                    pub.run_at = now + timedelta(seconds=e.retry_after + 1)
                    outcome = DeliveryOutcome(ok=False, channel_title=title, error="err.retry_later")
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
        if key == "notify.paused":
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=t("btn.pay", locale=owner.lang), callback_data=Bl(a="open").pack())
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
        async with self.sessionmaker() as session:
            users = (await session.scalars(
                select(User)
                .where(
                    User.trial_reminded.is_(False),
                    User.is_blocked.is_(False),
                    User.trial_ends_at > now,
                    User.trial_ends_at <= now + timedelta(days=1),
                )
                .limit(BATCH)
            )).all()
            to_notify = []
            for user in users:
                user.trial_reminded = True
                access = await get_access(session, user, now)
                if access.kind == "trial":
                    to_notify.append((user.tg_id, user.lang))
            await session.commit()
        for tg_id, lang in to_notify:
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=t("btn.pay", locale=lang), callback_data=Bl(a="open").pack())
            ]])
            try:
                await self.bot.send_message(tg_id, t("notify.trial_ending", locale=lang), reply_markup=markup)
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
                InlineKeyboardButton(text=t("btn.pay", locale=lang), callback_data=Bl(a="open").pack())
            ]])
            try:
                await self.bot.send_message(tg_id, t("notify.sub_ending", locale=lang), reply_markup=markup)
            except TelegramAPIError as e:
                log.info("subscription reminder not delivered: %s", e)
