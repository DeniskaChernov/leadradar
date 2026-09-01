from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
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
    telegram_manager_chat_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    telegram_viewer_chat_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    ai_mode: str = "hybrid"
    openai_live_calls_enabled: bool = False
    openai_daily_request_limit: int = Field(default=25, ge=0, le=10000)
    ai_pending_retry_enabled: bool = False
    ai_pending_retry_batch_size: int = Field(default=5, ge=0, le=100)
    ai_pending_retry_cooldown_seconds: int = Field(default=3600, ge=60)
    ai_request_lease_seconds: int = Field(default=180, ge=30, le=3600)
    ai_request_max_attempts: int = Field(default=3, ge=1, le=20)
    ai_analysis_max_concurrency: int = Field(default=3, ge=1, le=10)
    ai_analysis_poll_seconds: int = Field(default=5, ge=2, le=60)
    lead_analysis_version: str = "3.2"

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
    web_display_timezone: str = "Asia/Tashkent"
    web_public_url: str = ""
    web_manager_id: int = 0
    web_auth_enabled: bool = False
    telegram_init_data_max_age_seconds: int = Field(default=300, ge=60, le=3600)
    log_level: str = "INFO"
    http_timeout_seconds: float = Field(default=60.0, gt=0)
    http_max_attempts: int = Field(default=3, ge=1, le=5)
    telegram_notification_max_attempts: int = Field(default=3, ge=1, le=10)
    telegram_notification_flush_interval_seconds: int = Field(default=30, ge=10, le=3600)
    telegram_notification_lease_seconds: int = Field(default=120, ge=30, le=1800)
    notification_policy: str = "ALL_NEW_COMMENTS"
    external_kill_switch: bool = True

    meta_ads_access_token: str = ""
    meta_ads_ad_account_id: str = ""
    meta_ads_live_calls_enabled: bool = False

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

    @property
    def meta_ads_live_enabled(self) -> bool:
        if self.external_kill_switch:
            return False
        return (
            self.meta_ads_live_calls_enabled
            and self.external_spend_unlocked
            and bool(self.meta_ads_access_token.strip())
            and bool(self.meta_ads_ad_account_id.strip())
        )


    @field_validator(
        "telegram_admin_chat_ids",
        "telegram_manager_chat_ids",
        "telegram_viewer_chat_ids",
        mode="before",
    )
    @classmethod
    def parse_telegram_user_ids(cls, value: object) -> object:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        return value

    @field_validator("web_display_timezone")
    @classmethod
    def validate_web_display_timezone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        key = value.strip()
        if not key:
            raise ValueError("WEB_DISPLAY_TIMEZONE не может быть пустым")
        try:
            ZoneInfo(key)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Неизвестный часовой пояс: {key}") from exc
        return key

    @model_validator(mode="after")
    def apply_platform_port(self) -> Settings:
        import os

        port = os.environ.get("PORT", "").strip()
        if port.isdigit():
            self.web_port = int(port)
        return self

    @model_validator(mode="after")
    def validate_web_security_boundary(self) -> Settings:
        public_host = self.web_host.strip().lower() not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        public_url_host = (
            (urlparse(self.web_public_url).hostname or "").lower()
            if self.web_public_url
            else ""
        )
        public_url = bool(public_url_host) and public_url_host not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        publicly_exposed = public_host or public_url

        if publicly_exposed and not self.web_auth_enabled:
            raise ValueError("Public WEB_HOST/WEB_PUBLIC_URL requires WEB_AUTH_ENABLED=true")
        if publicly_exposed and not self.web_public_url.startswith("https://"):
            raise ValueError("Public web access requires an HTTPS WEB_PUBLIC_URL")
        if self.web_auth_enabled:
            if not self.telegram_bot_token:
                raise ValueError("WEB_AUTH_ENABLED=true requires TELEGRAM_BOT_TOKEN")
            access_ids = (
                set(self.telegram_admin_chat_ids)
                | set(self.telegram_manager_chat_ids)
                | set(self.telegram_viewer_chat_ids)
            )
            if not access_ids:
                raise ValueError("WEB_AUTH_ENABLED=true requires at least one allowed Telegram ID")
            role_sets = (
                set(self.telegram_admin_chat_ids),
                set(self.telegram_manager_chat_ids),
                set(self.telegram_viewer_chat_ids),
            )
            if any(role_sets[index] & role_sets[other] for index in range(3) for other in range(index + 1, 3)):
                raise ValueError("A Telegram ID must belong to exactly one web role")
        return self

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
