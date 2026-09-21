from __future__ import annotations

from datetime import timedelta

from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.config import Settings
from flowpost.db.models import User
from flowpost.db.types import utcnow
from flowpost.i18n import detect_lang

# `last_seen_at` only feeds the «active this week» stat, so it's written at most this often: without it
# every single update — every keystroke in the editor, every photo of an album — is a write to `users`.
LAST_SEEN_PRECISION = timedelta(minutes=5)


async def get_by_tg(session: AsyncSession, tg_id: int) -> User | None:
    return await session.scalar(select(User).where(User.tg_id == tg_id))


async def get_or_create(session: AsyncSession, tg_user: TgUser, settings: Settings) -> tuple[User, bool]:
    now = utcnow()
    user = await get_by_tg(session, tg_user.id)
    if user is not None:
        user.username = tg_user.username
        user.first_name = tg_user.first_name
        if user.last_seen_at is None or now - user.last_seen_at >= LAST_SEEN_PRECISION:
            user.last_seen_at = now
        if user.is_blocked:
            user.is_blocked = False
        return user, False

    user = User(
        tg_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
        lang=detect_lang(tg_user.language_code, settings.default_lang),
        tz=settings.default_tz,
        trial_ends_at=now + timedelta(days=settings.trial_days),
        created_at=now,
        last_seen_at=now,
    )
    try:
        async with session.begin_nested():
            session.add(user)
    except IntegrityError:
        # Another update of the same new user (e.g. an album) created the row concurrently.
        existing = await get_by_tg(session, tg_user.id)
        assert existing is not None
        return existing, False
    return user, True
