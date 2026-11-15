"""Typed application settings loaded from environment variables."""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = ""
    supabase_service_role_key: str = ""

    credential_encryption_key: str = ""
    api_key_secret: str = ""

    cors_origins: str = "http://localhost:5173"
    public_api_url: str = ""

    # Exchanges whose PUBLIC market data (no API keys) the engine scans 24/7.
    # Some hosts are geo-blocked from some Railway regions (Binance/Bybit from
    # the US), so each exchange is isolated and reports its own status.
    public_exchanges: str = "okx,bitget,mexc,bybit,binance"
    scan_interval_seconds: int = 30

    @property
    def market_exchanges(self) -> List[str]:
        return [e.strip().lower() for e in self.public_exchanges.split(",") if e.strip()]

    @property
    def allowed_origins(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()