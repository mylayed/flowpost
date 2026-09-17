from datetime import timedelta

from flowpost.bot.handlers.channels import _grant_trial_quotas
from flowpost.config import Settings
from flowpost.db.models import Payment, Subscription, User
from flowpost.db.types import utcnow
from flowpost.services.billing import limits
from flowpost.services.billing.liqpay import (
    LiqPayClient,
    decode_data,
    encode_data,
    make_signature,
    user_id_from_order,
    verify_signature,
)
from flowpost.services.billing.subscriptions import extend_subscription, get_access, record_payment
from flowpost.web import process_liqpay_payload
from sqlalchemy import func, select


def test_liqpay_signature_roundtrip():
    data = encode_data({"order_id": "flowpost-7-abc", "status": "success"})
    sig = make_signature("private", data)
    assert verify_signature("private", data, sig)
    assert not verify_signature("other", data, sig)
    assert decode_data(data)["order_id"] == "flowpost-7-abc"
    assert user_id_from_order("flowpost-7-abc") == 7
    assert user_id_from_order("something-else") is None


def test_liqpay_client_parses_only_signed_callbacks():
    client = LiqPayClient("pub", "priv", sandbox=True)
    data = encode_data({"order_id": "flowpost-3-abc", "status": "subscribed"})
    assert client.parse_callback(data, make_signature("priv", data)) == decode_data(data)
    assert client.parse_callback(data, "forged") is None


async def test_access_trial_then_paid(sessionmaker, seeded):
    async with sessionmaker() as session:
        user = await session.get(User, seeded.user_id)
        assert (await get_access(session, user)).kind == "trial"
        user.trial_ends_at = utcnow() - timedelta(minutes=1)
        assert not (await get_access(session, user)).active
        sub = await extend_subscription(session, user.id, "liqpay", days=30)
        assert sub.status == "active"
        access = await get_access(session, user)
        assert access.kind == "paid" and access.until > utcnow() + timedelta(days=29)
        # extending again stacks on top of the current period
        sub = await extend_subscription(session, user.id, "liqpay", days=30)
        assert sub.current_period_end > utcnow() + timedelta(days=59)


async def test_record_payment_is_idempotent(sessionmaker, seeded):
    async with sessionmaker() as session:
        kw = dict(user_id=seeded.user_id, provider="liqpay", amount=5, currency="USD", provider_payment_id="liqpay:1",
                  status="paid", raw={})
        assert await record_payment(session, **kw)
        assert not await record_payment(session, **kw)


async def test_liqpay_callback_processing(sessionmaker, seeded):
    payload = {"status": "success", "order_id": f"flowpost-{seeded.user_id}-abc", "payment_id": 999,
               "amount": 5, "currency": "USD"}
    assert await process_liqpay_payload(payload, sessionmaker, None) == "extended"
    assert await process_liqpay_payload(payload, sessionmaker, None) == "duplicate"
    async with sessionmaker() as session:
        sub = await session.scalar(select(Subscription).where(Subscription.user_id == seeded.user_id))
        assert sub.provider == "liqpay" and sub.provider_sub_id == payload["order_id"]
        assert await session.scalar(select(func.count(Payment.id))) == 1
    cancel = {**payload, "status": "unsubscribed", "payment_id": 1000}
    assert await process_liqpay_payload(cancel, sessionmaker, None) == "cancelled"


async def test_grant_trial_quotas_only_on_creation(sessionmaker, seeded):
    settings = Settings(bot_token="1:x", _env_file=None)
    async with sessionmaker() as session:
        await _grant_trial_quotas(session, settings, seeded.channel_id, created=True)
        await session.commit()
    async with sessionmaker() as session:
        left = await limits.remaining(session, seeded.channel_id)
        assert left == {"wm_photo": 15, "wm_video": 15, "ai_text": 15}

    # Reconnecting the same channel (created=False) must not top it up again.
    async with sessionmaker() as session:
        await _grant_trial_quotas(session, settings, seeded.channel_id, created=False)
        await session.commit()
    async with sessionmaker() as session:
        assert (await limits.remaining(session, seeded.channel_id))["wm_photo"] == 15
