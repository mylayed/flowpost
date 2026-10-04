"""The bot owner (`ADMIN_IDS`) isn't held to any plan: no post, AI or quota limits on their own channels."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.config import Settings, get_settings
from flowpost.db.models import User

# What the quota screens show for an owner with no limits.
UNLIMITED_QUOTA = 999_999


def is_unlimited(user: User | None, settings: Settings | None = None) -> bool:
    return user is not None and user.tg_id in (settings or get_settings()).admin_id_set


async def owner_unlimited(session: AsyncSession, owner_id: int, settings: Settings | None = None) -> bool:
    return is_unlimited(await session.get(User, owner_id), settings)
