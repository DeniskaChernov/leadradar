from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class OutboundNetworkForbiddenError(RuntimeError):
    """Raised when an automated test or kill-switch triggers against an outbound network call."""



class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    telegram_bot_token: str = ""
    external_live_unlock: str = ""
    telegram_admin_chat_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    ai_mode: str = "hybrid"
    openai_live_calls_enabled: bool = False
    openai_daily_request_limit: int = Field(default=25, ge=0, le=10000)
    ai_pending_retry_enabled: bool = False
    ai_pending_retry_batch_size: int = Field(default=5, ge=0, le=100)
    ai_pending_retry_cooldown_seconds: int = Field(default=3600, ge=60)

    scrapecreators_api_key: str = ""
    scrapecreators_api_url: str = "https://api.scrapecreators.com"

    brightdata_api_key: str = ""
    brightdata_api_url: str = "https://api.brightdata.com/datasets/v3/scrape"
    brightdata_profile_dataset_id: str = "gd_l1vikfch901nx3by4"
    brightdata_posts_dataset_id: str = "gd_lk5ns7kz21pck8jpis"
    brightdata_reels_dataset_id: str = "gd_lyclm20il4r5helnj"
    brightdata_comments_dataset_id: str = "gd_ltppn085pokosxh13"

    database_url: str = "sqlite+aiosqlite:///./lead_radar.db"
    database_backup_on_start: bool = True
    database_backup_keep: int = Field(default=10, ge=1, le=100)
    competitors: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["aiko.uz"]
    )
    instagram_provider: str = "replay"
    replay_fixture_path: str = "fixtures/replay_aiko.json"
    replay_state_path: str = ".runtime/replay_state.json"
    instagram_live_calls_enabled: bool = False
    instagram_daily_request_limit: int = Field(default=100, ge=0, le=100000)
    instagram_max_units_per_scan: int = Field(default=8, ge=0, le=1000)
    instagram_manual_live_scan_only: bool = True
    lead_search_enabled: bool = False
    monitor_schedule_enabled: bool = False
    hot_lead_threshold: int = Field(default=70, ge=0, le=100)
    instagram_poll_interval_seconds: int = Field(default=180, ge=10)
    # For incomplete history only. FULL posts with unchanged comment_count are not refetched.
    instagram_force_refresh_seconds: int = Field(default=21600, ge=0)
    instagram_auto_repair_partial_coverage: bool = False
    instagram_baseline_max_comment_pages: int = Field(default=1, ge=1, le=20)
    instagram_incremental_max_comment_pages: int = Field(default=2, ge=1, le=20)
    scrapecreators_max_comment_pages: int = Field(default=10, ge=1, le=100)
    process_existing_comments: bool = False
    analyze_baseline_comments: bool = True
    historical_analysis_batch_size: int = Field(default=25, ge=0, le=500)
    web_enabled: bool = True
    web_host: str = "127.0.0.1"
    web_port: int = Field(default=8000, ge=1, le=65535)
    web_public_url: str = ""
    web_manager_id: int = 0
    web_auth_enabled: bool = False
    telegram_init_data_max_age_seconds: int = Field(default=86400, ge=60, le=604800)
    log_level: str = "INFO"
    http_timeout_seconds: float = Field(default=60.0, gt=0)
    http_max_attempts: int = Field(default=3, ge=1, le=5)
    telegram_notification_max_attempts: int = Field(default=3, ge=1, le=10)
    telegram_notification_flush_interval_seconds: int = Field(default=30, ge=10, le=3600)
    telegram_notification_lease_seconds: int = Field(default=120, ge=30, le=1800)
    notification_policy: str = "ALL_NEW_COMMENTS"
    external_kill_switch: bool = False

    @property
    def external_spend_unlocked(self) -> bool:
        if self.external_kill_switch:
            return False
        return self.external_live_unlock.strip() == "ALLOW_EXTERNAL_CALLS"

    @property
    def instagram_live_enabled(self) -> bool:
        if self.external_kill_switch:
            return False
        return self.instagram_live_calls_enabled and self.external_spend_unlocked

    @property
    def openai_live_enabled(self) -> bool:
        if self.external_kill_switch:
            return False
        return self.openai_live_calls_enabled and self.external_spend_unlocked


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
        if normalized not in {"mock", "replay", "scrapecreators", "brightdata"}:
            raise ValueError("INSTAGRAM_PROVIDER must be mock, replay, scrapecreators, or brightdata")
        return normalized

    @field_validator("ai_mode")
    @classmethod
    def validate_ai_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"rules", "hybrid", "openai"}:
            raise ValueError("AI_MODE must be rules, hybrid, or openai")
        return normalized

    @field_validator("notification_policy")
    @classmethod
    def validate_notification_policy(cls, value: str) -> str:
        normalized = value.strip().upper()
        allowed = {"ALL_NEW_COMMENTS", "COMMERCIAL_ONLY", "HOT_ONLY"}
        if normalized not in allowed:
            raise ValueError(f"NOTIFICATION_POLICY must be one of: {', '.join(sorted(allowed))}")
        return normalized


def normalize_instagram_handle(value: str) -> str:
    handle = value.strip().lower().lstrip("@").rstrip("/")
    if "instagram.com/" in handle:
        handle = handle.split("instagram.com/", maxsplit=1)[1].split("/", maxsplit=1)[0]
    return handle


@lru_cache
def get_settings() -> Settings:
    return Settings()
