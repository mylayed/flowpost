"""LiqPay (API v3) monthly subscription: checkout link, callback verification, unsubscribe."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp

CHECKOUT_URL = "https://www.liqpay.ua/api/3/checkout"
REQUEST_URL = "https://www.liqpay.ua/api/request"

# Statuses that mean money was received (or a sandbox imitation of it).
PAID_STATUSES = {"success", "subscribed", "sandbox"}
CANCEL_STATUSES = {"unsubscribed"}
FAIL_STATUSES = {"failure", "error", "reversed"}


def encode_data(params: dict) -> str:
    return base64.b64encode(json.dumps(params, ensure_ascii=False).encode("utf-8")).decode("ascii")


def make_signature(private_key: str, data: str) -> str:
    digest = hashlib.sha1((private_key + data + private_key).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_signature(private_key: str, data: str, signature: str) -> bool:
    return hmac.compare_digest(make_signature(private_key, data), signature or "")


def decode_data(data: str) -> dict:
    return json.loads(base64.b64decode(data).decode("utf-8"))


def make_order_id(user_id: int) -> str:
    return f"flowpost-{user_id}-{uuid.uuid4().hex[:12]}"


def user_id_from_order(order_id: str) -> int | None:
    parts = (order_id or "").split("-")
    if len(parts) >= 3 and parts[0] == "flowpost" and parts[1].isdigit():
        return int(parts[1])
    return None


@dataclass
class LiqPayClient:
    public_key: str
    private_key: str
    sandbox: bool = False

    def checkout_url(
        self,
        *,
        user_id: int,
        amount: float,
        currency: str,
        description: str,
        language: str,
        server_url: str | None,
        result_url: str | None,
        now: datetime | None = None,
    ) -> str:
        now = now or datetime.now(timezone.utc)
        params = {
            "version": 3,
            "public_key": self.public_key,
            "action": "subscribe",
            "subscribe": "1",
            "subscribe_date_start": now.strftime("%Y-%m-%d %H:%M:%S"),
            "subscribe_periodicity": "month",
            "amount": f"{amount:.2f}",
            "currency": currency,
            "description": description,
            "order_id": make_order_id(user_id),
            "language": "uk" if language == "uk" else "en",
        }
        if server_url:
            params["server_url"] = server_url
        if result_url:
            params["result_url"] = result_url
        if self.sandbox:
            params["sandbox"] = "1"
        data = encode_data(params)
        signature = make_signature(self.private_key, data)
        return f"{CHECKOUT_URL}?data={data}&signature={signature}"

    def parse_callback(self, data: str, signature: str) -> dict | None:
        if not verify_signature(self.private_key, data, signature):
            return None
        return decode_data(data)

    async def unsubscribe(self, order_id: str) -> dict:
        params = {"version": 3, "public_key": self.public_key, "action": "unsubscribe", "order_id": order_id}
        data = encode_data(params)
        form = {"data": data, "signature": make_signature(self.private_key, data)}
        async with aiohttp.ClientSession() as http:
            async with http.post(REQUEST_URL, data=form, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                return await resp.json(content_type=None)
