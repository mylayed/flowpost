"""Trial/subscription access rules and payment bookkeeping."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import Payment, Publication, Subscription, User
from flowpost.db.types import utcnow

PERIOD_DAYS = 30


@dataclass
class Access:
    active: bool
    kind: str  # trial | paid | none
    until: datetime | None
    sub: Subscription | None


async def get_subscription(session: AsyncSession, user_id: int) -> Subscription | None:
    return await session.scalar(select(Subscription).where(Subscription.user_id == user_id))


async def get_access(session: AsyncSession, user: User, now: datetime | None = None) -> Access:
    now = now or utcnow()
    sub = await get_subscription(session, user.id)
    if sub and sub.status in ("active", "cancelled") and sub.current_period_end > now:
        return Access(True, "paid", sub.current_period_end, sub)
    if user.trial_ends_at and user.trial_ends_at > now:
        return Access(True, "trial", user.trial_ends_at, sub)
    return Access(False, "none", None, sub)


async def resume_paused(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        update(Publication)
        .where(Publication.owner_id == user_id, Publication.status == "paused")
        .values(status="pending")
    )


async def extend_subscription(
    session: AsyncSession,
    user_id: int,
    provider: str,
    *,
    until: datetime | None = None,
    days: int | None = None,
    provider_sub_id: str | None = None,
    now: datetime | None = None,
) -> Subscription:
    now = now or utcnow()
    sub = await get_subscription(session, user_id)
    if sub is None:
        sub = Subscription(user_id=user_id, provider=provider, status="active", current_period_end=now)
        session.add(sub)
    current_end = sub.current_period_end or now
    if until is not None:
        new_end = max(until, current_end)
    else:
        base = max(now, current_end) if (days or 0) > 0 else current_end
        new_end = base + timedelta(days=days if days is not None else PERIOD_DAYS)
    sub.provider = provider
    sub.status = "active" if new_end > now else "expired"
    sub.current_period_end = new_end
    sub.renewal_reminded = False
    if provider_sub_id:
        sub.provider_sub_id = provider_sub_id
    await session.flush()
    if sub.status == "active":
        await resume_paused(session, user_id)
    return sub


async def record_payment(
    session: AsyncSession,
    *,
    user_id: int,
    provider: str,
    amount: float,
    currency: str,
    provider_payment_id: str,
    status: str,
    raw: dict,
) -> bool:
    """Store a payment once. Returns False if this provider payment id was already processed."""
    exists = await session.scalar(select(Payment.id).where(Payment.provider_payment_id == provider_payment_id))
    if exists:
        return False
    session.add(
        Payment(
            user_id=user_id,
            provider=provider,
            amount=amount,
            currency=currency,
            provider_payment_id=provider_payment_id,
            status=status,
            raw=raw,
        )
    )
    await session.flush()
    return True
