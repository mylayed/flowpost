from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Channel, ChatTrial, Publication, UsageEvent, User
from flowpost.db.repo import channel_admins as channel_admins_repo
from flowpost.db.types import utcnow


async def list_channels(
    session: AsyncSession, owner_id: int, active_only: bool = True, *,
    perm: str | None = None, exclude_discussion_groups: bool = True,
) -> list[Channel]:
    """Channels `owner_id` owns, plus (if `perm`) channels delegated to them with that admin permission.

    A group linked to some channel purely as its comments/discussion group (`Channel.discussion_chat_id`)
    isn't itself a postable project, so it's excluded by default.
    """
    condition = Channel.owner_id == owner_id
    if perm:
        admin_ids = await channel_admins_repo.administered_channel_ids(session, owner_id, perm=perm)
        if admin_ids:
            condition = condition | Channel.id.in_(admin_ids)
    stmt = select(Channel).where(condition)
    if active_only:
        stmt = stmt.where(Channel.is_active.is_(True))
    if exclude_discussion_groups:
        discussion_ids = select(Channel.discussion_chat_id).where(Channel.discussion_chat_id.is_not(None))
        # A group's chat_id can drift from what's stored as `discussion_chat_id` (Telegram assigns a
        # new one when a basic group migrates to a supergroup) — matching by title too catches the
        # stale duplicate that leaves behind, without needing the link redone.
        discussion_titles = select(Channel.discussion_title).where(
            Channel.owner_id == owner_id, Channel.discussion_title.is_not(None), Channel.discussion_title != "",
        )
        stmt = stmt.where(
            Channel.chat_id.not_in(discussion_ids)
            & ~((Channel.kind == "group") & Channel.title.in_(discussion_titles))
        )
    channels = list((await session.scalars(stmt.order_by(Channel.created_at, Channel.id))).all())
    # Channels the owner pinned in «Інтерфейс → Канали → Порядок каналів» come first, in that order.
    order = await session.scalar(select(User.channel_order).where(User.id == owner_id)) or []
    rank = {channel_id: i for i, channel_id in enumerate(order)}
    channels.sort(key=lambda c: rank.get(c.id, len(rank)))
    return channels


async def get_channel(session: AsyncSession, owner_id: int, channel_id: int) -> Channel | None:
    channel = await session.scalar(select(Channel).where(Channel.id == channel_id))
    if channel is None:
        return None
    if channel.owner_id == owner_id:
        return channel
    if await channel_admins_repo.has_any_access(session, channel_id, owner_id):
        return channel
    return None


async def get_by_ids(session: AsyncSession, owner_id: int, ids: list[int]) -> list[Channel]:
    if not ids:
        return []
    admin_ids = await channel_admins_repo.administered_channel_ids(session, owner_id)
    rows = (await session.scalars(
        select(Channel).where(Channel.id.in_(ids), (Channel.owner_id == owner_id) | (Channel.id.in_(admin_ids)))
    )).all()
    by_id = {c.id: c for c in rows}
    return [by_id[i] for i in ids if i in by_id]


async def channels_by_chat(session: AsyncSession, chat_id: int) -> list[Channel]:
    return list((await session.scalars(select(Channel).where(Channel.chat_id == chat_id))).all())


async def is_discussion_group(session: AsyncSession, chat_id: int) -> bool:
    """Whether `chat_id` is designated (by any owner) as some channel's comments/discussion group."""
    return bool(await session.scalar(select(Channel.id).where(Channel.discussion_chat_id == chat_id).limit(1)))


async def upsert_channel(
    session: AsyncSession,
    owner_id: int,
    *,
    chat_id: int,
    kind: str,
    title: str,
    username: str | None,
    is_forum: bool,
    trial_days: int,
) -> tuple[Channel, bool]:
    """Connect (or reconnect) a chat. `created` is True only the first time this chat is ever connected —
    a chat deleted from «Мої проєкти» and connected again gets its old trial back, not a new one, and so
    does a chat connected by a second account: the trial belongs to the chat, not to the connection."""
    trial, first_ever = await _chat_trial(session, chat_id, owner_id, trial_days)
    channel = await session.scalar(select(Channel).where(Channel.owner_id == owner_id, Channel.chat_id == chat_id))
    created = channel is None and first_ever
    if channel is None:
        channel = Channel(owner_id=owner_id, chat_id=chat_id, watermark={})
        session.add(channel)
    # The chat's registered trial is the authority: reconnecting never moves its end further away.
    channel.trial_ends_at = trial.trial_ends_at
    channel.kind = kind
    channel.title = title or str(chat_id)
    channel.username = username
    channel.is_forum = is_forum
    channel.is_active = True
    await session.flush()
    return channel, created


async def migrate_chat(session: AsyncSession, old_id: int, new_id: int) -> None:
    """A basic group became a supergroup and Telegram gave it a new chat_id: move everything kept under the old one.

    A project of the same owner that already exists under the new id (they connected the supergroup by hand
    before we noticed) can't take a second row, so the stale one is switched off instead of renamed.
    """
    if old_id == new_id:
        return
    taken = {c.owner_id for c in await channels_by_chat(session, new_id)}
    for channel in await channels_by_chat(session, old_id):
        if channel.owner_id in taken:
            channel.is_active = False
        else:
            channel.chat_id = new_id
    for channel in (await session.scalars(select(Channel).where(Channel.discussion_chat_id == old_id))).all():
        channel.discussion_chat_id = new_id
    trial = await get_chat_trial(session, old_id)
    if trial is not None and await get_chat_trial(session, new_id) is None:
        trial.chat_id = new_id  # the trial belongs to the chat, so it moves with it
    await session.flush()


async def get_chat_trial(session: AsyncSession, chat_id: int) -> ChatTrial | None:
    return await session.scalar(select(ChatTrial).where(ChatTrial.chat_id == chat_id))


async def _chat_trial(
    session: AsyncSession, chat_id: int, owner_id: int, trial_days: int
) -> tuple[ChatTrial, bool]:
    """The chat's trial, started here if the chat has never been connected before (then `first_ever`)."""
    trial = await get_chat_trial(session, chat_id)
    if trial is not None:
        return trial, False
    now = utcnow()
    trial = ChatTrial(
        chat_id=chat_id, started_at=now, trial_ends_at=now + timedelta(days=trial_days),
        posts_used=0, first_owner_id=owner_id,
    )
    try:
        async with session.begin_nested():
            session.add(trial)
            await session.flush()
    except IntegrityError:
        # chat_shared and my_chat_member arrive together — the other one registered the chat first.
        existing = await get_chat_trial(session, chat_id)
        assert existing is not None
        return existing, False
    return trial, True


async def reset_chat_trial(session: AsyncSession, chat_id: int, days: int) -> ChatTrial | None:
    """Give the chat a fresh trial of `days` (0 ends it now), on every account that has it connected."""
    trial = await get_chat_trial(session, chat_id)
    if trial is None:
        return None
    now = utcnow()
    trial.started_at = now
    trial.trial_ends_at = now + timedelta(days=days)
    trial.posts_used = 0
    for channel in await channels_by_chat(session, chat_id):
        channel.trial_ends_at = trial.trial_ends_at
    await session.flush()
    return trial


async def trial_posts_published(session: AsyncSession, channel_ids: list[int], trial: ChatTrial) -> int:
    """Posts these connections published while the chat's trial was running."""
    if not channel_ids:
        return 0
    return int(await session.scalar(
        select(func.count(Publication.id)).where(
            Publication.channel_id.in_(channel_ids),
            Publication.status == "published",
            Publication.published_at >= trial.started_at,
            Publication.published_at < trial.trial_ends_at,
        )
    ) or 0)


async def delete_channel(session: AsyncSession, channel: Channel) -> None:
    """Remove a project from the bot along with its settings, schedule and stats (FK cascades).

    The chat keeps its `ChatTrial`, with the trial posts it published booked onto it, so connecting the
    chat again neither restarts the trial nor hands out its post allowance a second time.
    """
    trial = await get_chat_trial(session, channel.chat_id)
    if trial is not None:
        trial.posts_used = (trial.posts_used or 0) + await trial_posts_published(session, [channel.id], trial)
    session.add(UsageEvent(
        user_id=channel.owner_id, kind="channel_deleted",
        meta={"chat_id": channel.chat_id,
              "trial_ends_at": channel.trial_ends_at.isoformat() if channel.trial_ends_at else None},
    ))
    owner = await session.get(User, channel.owner_id)
    if owner is not None and channel.id in (owner.channel_order or []):
        owner.channel_order = [c for c in owner.channel_order if c != channel.id]
    await session.delete(channel)
    await session.flush()
