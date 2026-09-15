"""Extra per-channel usage packs (watermarks, AI texts) bought from the Stars wallet on top of the plan."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import ChannelQuota
from flowpost.services import analytics
from flowpost.services.billing.wallet import debit

LIMIT_KINDS = ("wm_photo", "wm_video", "ai_text")


def public_prices(prices: dict[str, dict[int, int]]) -> dict[str, dict[str, int]]:
    return {
        kind: {str(size): prices[kind][size] for size in sorted(prices[kind])}
        for kind in LIMIT_KINDS
        if kind in prices
    }


def pack_total(prices: dict[str, dict[int, int]], packs: dict) -> int | None:
    """Price of the requested pack sizes, or None if a kind or size isn't on sale."""
    total = 0
    for kind, size in packs.items():
        if kind not in LIMIT_KINDS or kind not in prices or not isinstance(size, int) or isinstance(size, bool):
            return None
        if size == 0:
            continue
        if size not in prices[kind]:
            return None
        total += prices[kind][size]
    return total


async def remaining(session: AsyncSession, channel_id: int) -> dict[str, int]:
    left = {kind: 0 for kind in LIMIT_KINDS}
    for quota in await session.scalars(select(ChannelQuota).where(ChannelQuota.channel_id == channel_id)):
        if quota.kind in left:
            left[quota.kind] = quota.remaining
    return left


async def add(session: AsyncSession, channel_id: int, kind: str, amount: int) -> None:
    quota = await session.scalar(
        select(ChannelQuota).where(ChannelQuota.channel_id == channel_id, ChannelQuota.kind == kind).with_for_update()
    )
    if quota is None:
        quota = ChannelQuota(channel_id=channel_id, kind=kind, remaining=0)
        session.add(quota)
    quota.remaining += amount


async def take(session: AsyncSession, channel_id: int, kind: str, amount: int = 1) -> bool:
    """Spend `amount` of a channel's quota; False and no write if less than that remains."""
    quota = await session.scalar(
        select(ChannelQuota).where(ChannelQuota.channel_id == channel_id, ChannelQuota.kind == kind).with_for_update()
    )
    if quota is None or quota.remaining < amount:
        return False
    quota.remaining -= amount
    await session.flush()
    return True


async def buy_packs(session: AsyncSession, user_id: int, channel_id: int, packs: dict[str, int], total: int) -> bool:
    """Charge `total` from the wallet and add the packs to the channel; False if the wallet can't cover it."""
    if not await debit(session, user_id, total, kind="spend", ref=f"limits:{channel_id}"):
        return False
    for kind, size in packs.items():
        if size:
            await add(session, channel_id, kind, size)
    await session.flush()
    analytics.track(session, user_id, "limits", channel_id=channel_id, packs=packs, stars=total)
    return True
