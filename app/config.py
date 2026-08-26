from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    telegram_bot_token: str = ""
    telegram_admin_chat_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"

    scrapecreators_api_key: str = ""
    scrapecreators_api_url: str = "https://api.scrapecreators.com"

    brightdata_api_key: str = ""
    brightdata_api_url: str = "https://api.brightdata.com/datasets/v3/scrape"
    brightdata_profile_dataset_id: str = "gd_l1vikfch901nx3by4"
    brightdata_posts_dataset_id: str = "gd_lk5ns7kz21pck8jpis"
    brightdata_reels_dataset_id: str = "gd_lyclm20il4r5helnj"
    brightdata_comments_dataset_id: str = "gd_ltppn085pokosxh13"

    database_url: str = "sqlite+aiosqlite:///./lead_radar.db"
    competitors: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["aiko.uz"]
    )
    instagram_provider: str = "mock"
    hot_lead_threshold: int = Field(default=70, ge=0, le=100)
    instagram_poll_interval_seconds: int = Field(default=180, ge=10)
    process_existing_comments: bool = False
    log_level: str = "INFO"
    http_timeout_seconds: float = Field(default=60.0, gt=0)
    http_max_attempts: int = Field(default=3, ge=1, le=5)

    @field_validator("telegram_admin_chat_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> object:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        return value

    @field_validator("competitors", mode="before")
    @classmethod
    def parse_competitors(cls, value: object) -> object:
        if value in (None, ""):
            return ["aiko.uz"]
        if isinstance(value, str):
            return [normalize_instagram_handle(item) for item in value.split(",") if item.strip()]
        return value

    @field_validator("instagram_provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"mock", "scrapecreators", "brightdata"}:
            raise ValueError("INSTAGRAM_PROVIDER must be mock, scrapecreators, or brightdata")
        return normalized


def normalize_instagram_handle(value: str) -> str:
    handle = value.strip().lower().lstrip("@").rstrip("/")
    if "instagram.com/" in handle:
        handle = handle.split("instagram.com/", maxsplit=1)[1].split("/", maxsplit=1)[0]
    return handle


@lru_cache
def get_settings() -> Settings:
    return Settings()
