"""LiqPay (API v3) for legacy monthly subscriptions: callback verification and unsubscribe."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass

import aiohttp

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
