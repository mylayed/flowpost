"""Delegated channel access: invite links and the resulting ChannelAdmin grants."""
from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import ChannelAdmin, ChannelInvite, User
from flowpost.db.types import utcnow

PERM_COLUMNS = {"posts": ChannelAdmin.can_posts, "settings": ChannelAdmin.can_settings, "disconnect": ChannelAdmin.can_disconnect}


async def administered_channel_ids(session: AsyncSession, user_id: int, *, perm: str | None = None) -> set[int]:
    """Channel ids `user_id` was granted admin access to (optionally filtered to one permission)."""
    stmt = select(ChannelAdmin.channel_id).where(ChannelAdmin.user_id == user_id)
    if perm:
        stmt = stmt.where(PERM_COLUMNS[perm].is_(True))
    return set((await session.scalars(stmt)).all())


async def get_grant(session: AsyncSession, channel_id: int, user_id: int) -> ChannelAdmin | None:
    return await session.scalar(
        select(ChannelAdmin).where(ChannelAdmin.channel_id == channel_id, ChannelAdmin.user_id == user_id)
    )


async def has_permission(session: AsyncSession, channel_id: int, user_id: int, perm: str) -> bool:
    grant = await get_grant(session, channel_id, user_id)
    return bool(grant and getattr(grant, f"can_{perm}"))


async def has_any_access(session: AsyncSession, channel_id: int, user_id: int) -> bool:
    grant = await get_grant(session, channel_id, user_id)
    return bool(grant and (grant.can_posts or grant.can_settings or grant.can_disconnect))


async def list_admins(session: AsyncSession, channel_id: int) -> list[tuple[ChannelAdmin, User]]:
    rows = (await session.execute(
        select(ChannelAdmin, User)
        .join(User, User.id == ChannelAdmin.user_id)
        .where(ChannelAdmin.channel_id == channel_id)
        .order_by(ChannelAdmin.created_at)
    )).all()
    return [(admin, user) for admin, user in rows]


async def remove_admin(session: AsyncSession, channel_id: int, admin_id: int) -> bool:
    grant = await session.get(ChannelAdmin, admin_id)
    if grant is None or grant.channel_id != channel_id:
        return False
    await session.delete(grant)
    await session.flush()
    return True


async def create_invite(
    session: AsyncSession, channel_id: int, created_by: int, *, can_posts: bool, can_settings: bool, can_disconnect: bool,
) -> ChannelInvite:
    invite = ChannelInvite(
        channel_id=channel_id, token=secrets.token_hex(12), created_by=created_by,
        can_posts=can_posts, can_settings=can_settings, can_disconnect=can_disconnect,
    )
    session.add(invite)
    await session.flush()
    return invite


async def get_invite(session: AsyncSession, token: str, *, for_update: bool = False) -> ChannelInvite | None:
    stmt = select(ChannelInvite).where(ChannelInvite.token == token)
    if for_update:
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


async def redeem_invite(session: AsyncSession, invite: ChannelInvite, user_id: int) -> ChannelAdmin:
    existing = await session.scalar(
        select(ChannelAdmin).where(ChannelAdmin.channel_id == invite.channel_id, ChannelAdmin.user_id == user_id)
    )
    if existing is not None:
        existing.can_posts = existing.can_posts or invite.can_posts
        existing.can_settings = existing.can_settings or invite.can_settings
        existing.can_disconnect = existing.can_disconnect or invite.can_disconnect
        grant = existing
    else:
        grant = ChannelAdmin(
            channel_id=invite.channel_id, user_id=user_id,
            can_posts=invite.can_posts, can_settings=invite.can_settings, can_disconnect=invite.can_disconnect,
        )
        session.add(grant)
    invite.used_by = user_id
    invite.used_at = utcnow()
    await session.flush()
    return grant


def invite_permissions_label(invite: ChannelInvite) -> list[str]:
    perms = []
    if invite.can_posts:
        perms.append("posts")
    if invite.can_settings:
        perms.append("settings")
    if invite.can_disconnect:
        perms.append("disconnect")
    return perms
