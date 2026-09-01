from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InstagramProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_user_id: str | None = None
    username: str
    display_name: str | None = None
    profile_url: str
    raw_data: dict[str, Any] = Field(default_factory=dict)


class InstagramPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_post_id: str
    competitor: str
    url: str
    caption: str = ""
    post_type: str = "REEL"
    published_at: datetime | None = None
    comments_count: int = Field(default=0, ge=0)
    raw_data: dict[str, Any] = Field(default_factory=dict)


class InstagramComment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_comment_id: str
    platform_user_id: str | None = None
    username: str
    display_name: str | None = None
    profile_url: str
    text: str
    created_at: datetime | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)



class CommentFetchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comments: list[InstagramComment] = Field(default_factory=list)
    provider: str
    pages_fetched: int = Field(default=1, ge=0)
    coverage_status: str = "UNKNOWN"
    cursor_exhausted: bool = True
    stopped_on_known_comment: bool = False


class ProviderCreditObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str
    provider: str
    operation: str
    credits_remaining: int | None = Field(default=None, ge=0)
    credits_charged: int | None = Field(default=None, ge=0)
