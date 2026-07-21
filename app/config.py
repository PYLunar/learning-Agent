"""
Configuration and settings for the Travel Planning System.
"""

import os
from functools import lru_cache
from typing import Optional


def _clean_env_value(name: str, default: str = "") -> str:
    """Return empty string for common placeholder values in .env files."""
    value = os.getenv(name, default)
    if not value:
        return ""
    lowered = value.strip().lower()
    placeholders = ["需要你注册获取", "your-key", "your_key", "replace-me", "todo"]
    if any(p in lowered for p in placeholders):
        return ""
    return value


class Settings:
    """Application settings loaded from environment variables."""

    # LLM Configuration
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: Optional[str] = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "4000"))

    # Mock mode: if True, use mock responses instead of real LLM calls
    MOCK_MODE: bool = os.getenv("MOCK_MODE", "false").lower() == "true"

    # API Keys for external services
    WEATHER_API_KEY: Optional[str] = _clean_env_value("WEATHER_API_KEY")
    GOOGLE_MAPS_API_KEY: Optional[str] = _clean_env_value("GOOGLE_MAPS_API_KEY")
    GOOGLE_SEARCH_API_KEY: Optional[str] = _clean_env_value("GOOGLE_SEARCH_API_KEY")
    GOOGLE_SEARCH_CX: Optional[str] = _clean_env_value("GOOGLE_SEARCH_CX")
    WIKIPEDIA_ENABLED: bool = os.getenv("WIKIPEDIA_ENABLED", "true").lower() == "true"

    # China-specific API Keys (中国本土化)
    AMAP_KEY: Optional[str] = _clean_env_value("AMAP_KEY")
    QWEATHER_KEY: Optional[str] = _clean_env_value("QWEATHER_KEY")
    BING_SEARCH_API_KEY: Optional[str] = _clean_env_value("BING_SEARCH_API_KEY")

    # Cache settings
    CACHE_ENABLED: bool = os.getenv("CACHE_ENABLED", "true").lower() == "true"
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "3600"))

    # Retry settings
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_DELAY_SECONDS: float = float(os.getenv("RETRY_DELAY_SECONDS", "1.0"))
    FLYAI_TIMEOUT_SECONDS: float = float(os.getenv("FLYAI_TIMEOUT_SECONDS", "12"))
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
    PLAN_TIMEOUT_SECONDS: float = float(os.getenv("PLAN_TIMEOUT_SECONDS", "75"))
    ENABLE_LLM_ENHANCEMENT: bool = os.getenv("ENABLE_LLM_ENHANCEMENT", "false").lower() == "true"

    # Application settings
    APP_NAME: str = "AI Travel Agent"
    APP_VERSION: str = "1.0.0"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    DEFAULT_ORIGIN: str = os.getenv("DEFAULT_ORIGIN", "北京")

    # Multi-language
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE", "zh")
    SUPPORTED_LANGUAGES: list = ["zh", "en"]


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
