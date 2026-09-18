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
    # Supergroup with Topics where every user who writes to «Підтримка» gets their own topic; whatever the team
    # writes in that topic goes back to the user from the bot. Empty = support messages go to ADMIN_IDS in private.
    support_chat_id: int | None = None
    # Premium (custom) emoji in posts. Telegram lets only bots that bought a username on Fragment send
    # them; while this is off every <tg-emoji> is replaced by the plain emoji inside it at send time.
    premium_emoji: bool = False

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
    trial_days: int = 30
    # LiqPay only processes renewals and cancellations of subscriptions bought before the Stars Mini App.
    liqpay_enabled: bool = True
    liqpay_public_key: str = ""
    liqpay_private_key: SecretStr = SecretStr("")
    liqpay_sandbox: bool = False

    # --- Billing Mini App (Telegram Stars wallet) ---
    webapp_enabled: bool = True
    webapp_url_override: str | None = Field(None, validation_alias=AliasChoices("WEBAPP_URL", "WEBAPP_URL_OVERRIDE"))
    stars_topup_min: int = 1
    stars_topup_max: int = 25000
    stars_usd_rate: float = 0.02
    cashback_percent: float = 5.0
    renew_soon_days: int = 7  # channels expiring within this many days are listed under «Час продовжити»
    # Extra per-channel packs: kind -> {pack size: price in Stars}. Env: LIMIT_PRICES='{"wm_photo": {"10": 5}, ...}'
    limit_prices: dict[str, dict[int, int]] = {
        "wm_photo": {10: 5, 100: 15, 500: 49, 1000: 75},
        "wm_video": {10: 10, 100: 75, 500: 325, 1000: 599},
        "ai_text": {10: 10, 100: 29, 500: 129, 1000: 229},
    }
    # Posting plans: posts per day -> Stars and included watermarks/AI texts per channel per 30 days
    posting_plans: dict[int, dict[str, int]] = {
        1: {"stars": 75, "wm_photo": 30, "wm_video": 6, "ai_text": 30},
        15: {"stars": 124, "wm_photo": 450, "wm_video": 75, "ai_text": 450},
        50: {"stars": 199, "wm_photo": 1500, "wm_video": 250, "ai_text": 1500},
        150: {"stars": 349, "wm_photo": 4500, "wm_video": 750, "ai_text": 4500},
        500: {"stars": 499, "wm_photo": 15000, "wm_video": 2500, "ai_text": 15000},
    }
    channel_discounts: dict[int, int] = {3: 2, 5: 5, 10: 10, 20: 15, 30: 20, 50: 25, 100: 30}  # from N channels -> %
    term_discounts: dict[int, int] = {30: 0, 90: 10, 180: 15, 365: 20}  # days -> %
    # Stars pack sizes sold in @PremiumBot; checkout offers extra days to match the nearest pack exactly
    stars_packs: list[int] = [50, 75, 100, 150, 250, 350, 500, 750, 1000, 1500, 2500, 5000, 10000, 25000, 50000]
    trial_posts: int = 100
    # Account-wide subscriptions from before per-channel plans count as this plan on every channel of the account
    legacy_posts_per_day: int = 15
    trial_quotas: dict[str, int] = {"wm_photo": 15, "wm_video": 15, "ai_text": 15}
    free_posts_per_day: int = 10  # 0 = no free plan
    calc_max_channels: int = 100
    terms_url: str = ""  # empty = the built-in terms page (the /terms text)
    privacy_url: str = "https://telegram.org/privacy-tpa"

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
    def webapp_url(self) -> str | None:
        if not self.webapp_enabled:
            return None
        if self.webapp_url_override:
            return self.webapp_url_override
        if not self.webhook_base_url:
            return None
        return self.webhook_base_url.rstrip("/") + "/app/"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
