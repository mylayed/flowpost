"""Internal Stars wallet: a main balance topped up with Telegram Stars plus a cashback balance."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.db.models import BalanceEntry, User
from flowpost.services import analytics
from flowpost.services.billing.subscriptions import record_payment

BUCKET_COLUMNS = {"main": User.balance, "cashback": User.cashback}


def cashback_for(stars: int, percent: float) -> int:
    return int(stars * percent // 100)


async def credit(
    session: AsyncSession, user_id: int, amount: int, *, bucket: str, kind: str, ref: str | None = None
) -> None:
    column = BUCKET_COLUMNS[bucket]
    # Incremented in SQL so two concurrent credits to the same user can't overwrite each other.
    await session.execute(update(User).where(User.id == user_id).values({column: column + amount}))
    session.add(BalanceEntry(user_id=user_id, bucket=bucket, delta=amount, kind=kind, ref=ref))
    await session.flush()


async def debit(session: AsyncSession, user_id: int, amount: int, *, kind: str, ref: str | None = None) -> bool:
    """Spend `amount` Stars, cashback first. Returns False and writes nothing if the wallet can't cover it."""
    user = await session.scalar(
        select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
    )
    if user is None or amount <= 0 or user.balance + user.cashback < amount:
        return False
    from_cashback = min(user.cashback, amount)
    from_main = amount - from_cashback
    user.cashback -= from_cashback
    user.balance -= from_main
    for bucket, part in (("cashback", from_cashback), ("main", from_main)):
        if part:
            session.add(BalanceEntry(user_id=user_id, bucket=bucket, delta=-part, kind=kind, ref=ref))
    await session.flush()
    return True


async def apply_topup(
    session: AsyncSession, user_id: int, stars: int, charge_id: str, raw: dict, cashback_percent: float
) -> int | None:
    """Credit a paid Stars top-up exactly once. Returns the cashback granted, or None for an already-applied charge."""
    ref = f"stars:{charge_id}"
    is_new = await record_payment(
        session, user_id=user_id, provider="stars", amount=float(stars), currency="XTR",
        provider_payment_id=ref, status="paid", raw=raw,
    )
    if not is_new:
        return None
    await credit(session, user_id, stars, bucket="main", kind="topup", ref=ref)
    bonus = cashback_for(stars, cashback_percent)
    if bonus:
        await credit(session, user_id, bonus, bucket="cashback", kind="cashback", ref=ref)
    analytics.track(session, user_id, "payment", provider="stars", amount=stars)
    return bonus
