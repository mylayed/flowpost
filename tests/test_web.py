from aiohttp.test_utils import TestClient, TestServer

from flowpost.config import Settings
from flowpost.services.billing.liqpay import encode_data, make_signature
from flowpost.web import build_web_app


async def _client(settings: Settings, sessionmaker) -> TestClient:
    client = TestClient(TestServer(build_web_app(settings, None, sessionmaker)))  # type: ignore[arg-type]
    await client.start_server()
    return client


async def test_health(settings, sessionmaker):
    client = await _client(settings, sessionmaker)
    try:
        resp = await client.get("/health")
        assert resp.status == 200 and (await resp.json()) == {"status": "ok"}
    finally:
        await client.close()


async def test_liqpay_callback_disabled_and_bad_signature(sessionmaker):
    disabled = Settings(bot_token="1:x", _env_file=None)
    client = await _client(disabled, sessionmaker)
    try:
        assert (await client.post("/pay/liqpay/callback", data={"data": "x", "signature": "y"})).status == 404
    finally:
        await client.close()

    enabled = Settings(bot_token="1:x", liqpay_enabled=True, liqpay_public_key="pub", liqpay_private_key="priv",
                       _env_file=None)
    client = await _client(enabled, sessionmaker)
    try:
        data = encode_data({"status": "success", "order_id": "flowpost-1-abc", "payment_id": 1})
        bad = await client.post("/pay/liqpay/callback", data={"data": data, "signature": "forged"})
        assert bad.status == 400
        good = await client.post("/pay/liqpay/callback", data={"data": data, "signature": make_signature("priv", data)})
        assert good.status == 200 and await good.text() == "ok"
    finally:
        await client.close()
