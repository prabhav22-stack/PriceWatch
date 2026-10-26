"""Application configuration managed via Pydantic BaseSettings."""

from typing import List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.secrets"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = Field(default="", description="Telegram Bot API Token")
    TELEGRAM_WEBHOOK_SECRET: str = Field(default="", description="Secret token for Telegram webhook validation")
    TELEGRAM_ADMIN_USER_IDS: List[int] = Field(default_factory=list, description="List of Admin Telegram IDs")
    WEBHOOK_BASE_URL: str = Field(default="", description="Base public URL for Render webhook")

    # Database & Supabase
    DATABASE_URL: str = Field(default="", description="PostgreSQL transaction pooler connection URL")
    SUPABASE_URL: str = Field(default="", description="Supabase project URL")
    SUPABASE_KEY: str = Field(default="", description="Supabase service role or anon key")
    SUPABASE_ACCESS_TOKEN: str = Field(default="", description="Supabase Management API access token")

    # Application & Environment
    APP_ENV: str = Field(default="development", description="Environment: development | staging | production")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    RENDER_HEALTHZ_URL: str = Field(default="", description="Render health check endpoint URL")

    # Scheduling & Worker Concurrency
    HTTP_BATCH_SIZE: int = Field(default=40, description="Max listings to claim per HTTP check run")
    BROWSER_BATCH_SIZE: int = Field(default=15, description="Max listings to claim per Playwright run")
    DEFAULT_CHECK_INTERVAL_MINUTES: int = Field(default=15, description="Standard check interval in minutes")
    WORKER_LEASE_SECONDS: int = Field(default=300, description="Database lease lock duration in seconds")
    MAX_CONSECUTIVE_FAILURES: int = Field(default=10, description="Max consecutive failures before backoff")

    # Alerting & Thresholds
    HYSTERESIS_REARM_PCT: int = Field(default=3, description="Percent price rise above target to re-arm alert")
    NOTIFY_ON_FURTHER_DROP_PCT: int = Field(default=2, description="Minimum drop percentage to re-trigger alert")
    MAX_ITEMS_PER_USER: int = Field(default=20, description="Maximum active tracked products per user")

    @field_validator("TELEGRAM_ADMIN_USER_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v or []


# Global cached settings instance
settings = Settings()
