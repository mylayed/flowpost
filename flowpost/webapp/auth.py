"""Validation of Mini App initData: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

MAX_AGE_SECONDS = 24 * 3600


def validate_init_data(
    init_data: str, bot_token: str, *, max_age: int = MAX_AGE_SECONDS, now: float | None = None
) -> dict | None:
    """The signed Telegram user, or None if initData is forged, malformed or older than `max_age`."""
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    received = fields.pop("hash", "")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not received or not hmac.compare_digest(expected, received):
        return None
    try:
        auth_date = int(fields.get("auth_date", ""))
        user = json.loads(fields["user"])
    except (ValueError, KeyError):
        return None
    if (time.time() if now is None else now) - auth_date > max_age:
        return None
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        return None
    return user
