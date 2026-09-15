"""Tracking channel-post reactions for the per-channel analytics view."""
from __future__ import annotations

from aiogram import Router
from aiogram.types import MessageReactionCountUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.repo import channels as channels_repo
from flowpost.db.repo import publications as pubs_repo

router = Router(name="reactions")


@router.message_reaction_count()
async def on_reaction_count(event: MessageReactionCountUpdated, session: AsyncSession) -> None:
    channels = await channels_repo.channels_by_chat(session, event.chat.id)
    if not channels:
        return
    counts = {r.type.emoji: r.total_count for r in event.reactions if r.type.type == "emoji"}
    for channel in channels:
        pub = await pubs_repo.find_by_channel_message(session, channel.owner_id, [channel.id], event.message_id)
        if pub is None:
            continue
        pub.reactions = {**(pub.reactions or {}), str(event.message_id): counts}
