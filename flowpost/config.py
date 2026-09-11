from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Telegram ---
    bot_token: SecretStr
    admin_ids: str = ""
    support_contact: str = ""

    # --- Storage ---
    database_url: str = "sqlite+aiosqlite:///./flowpost.db"
    redis_url: str | None = None

    # --- Localization ---
    default_lang: str = "uk"
    default_tz: str = "Europe/Kyiv"

    # --- Web / webhook ---
    webhook_base_url: str | None = None
    webhook_secret: str = ""
    web_host: str = "0.0.0.0"
    web_port: int = Field(8080, validation_alias=AliasChoices("PORT", "WEB_PORT"))

    # --- AI (Anthropic) ---
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5"
    ai_effort: str = "medium"
    ai_fallbacks: bool = True
    ai_daily_limit_trial: int = 20
    ai_daily_limit_paid: int = 150

    # --- Billing ---
    trial_days: int = 7
    sub_price_usd: float = 5.0
    stars_enabled: bool = True
    stars_price: int = 350
    liqpay_enabled: bool = False
    liqpay_public_key: str = ""
    liqpay_private_key: SecretStr = SecretStr("")
    liqpay_amount: float = 5.0
    liqpay_currency: str = "USD"
    liqpay_sandbox: bool = False

    # --- Media / worker ---
    ffmpeg_bin: str = "ffmpeg"
    watermark_font: str | None = None
    watermark_concurrency: int = 2
    worker_interval: int = 10
    missed_grace_hours: int = 2

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        # Railway/Heroku give "postgres://" or "postgresql://" — switch to the asyncpg driver.
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    @property
    def admin_id_set(self) -> set[int]:
        return {int(x) for x in self.admin_ids.replace(";", ",").split(",") if x.strip().lstrip("-").isdigit()}

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key and self.anthropic_api_key.get_secret_value())

    @property
    def webhook_url(self) -> str | None:
        if not self.webhook_base_url:
            return None
        return self.webhook_base_url.rstrip("/") + "/tg/webhook"

    @property
    def liqpay_callback_url(self) -> str | None:
        if not self.webhook_base_url:
            return None
        return self.webhook_base_url.rstrip("/") + "/pay/liqpay/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
