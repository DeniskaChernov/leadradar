from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ContactEventType(StrEnum):
    COMMENT_FOUND = "COMMENT_FOUND"
    LEAD_CREATED = "LEAD_CREATED"
    LEAD_SCORE_CHANGED = "LEAD_SCORE_CHANGED"
    MANAGER_ASSIGNED = "MANAGER_ASSIGNED"
    MANAGER_MARKED_NOT_LEAD = "MANAGER_MARKED_NOT_LEAD"
    CONTACTED = "CONTACTED"
    CUSTOMER_REPLIED = "CUSTOMER_REPLIED"
    NOTE_ADDED = "NOTE_ADDED"
    PRODUCT_INTEREST_ADDED = "PRODUCT_INTEREST_ADDED"
    OFFER_SENT = "OFFER_SENT"
    NEGOTIATION_STARTED = "NEGOTIATION_STARTED"
    DEAL_CREATED = "DEAL_CREATED"
    DEAL_WON = "DEAL_WON"
    DEAL_LOST = "DEAL_LOST"
    LEAD_STATUS_CHANGED = "LEAD_STATUS_CHANGED"
    NEXT_CONTACT_SCHEDULED = "NEXT_CONTACT_SCHEDULED"
    NEXT_CONTACT_COMPLETED = "NEXT_CONTACT_COMPLETED"
    NEXT_CONTACT_CANCELLED = "NEXT_CONTACT_CANCELLED"
    QUALIFICATION_UPDATED = "QUALIFICATION_UPDATED"
    LEAD_REOPENED = "LEAD_REOPENED"


class LeadStatus(StrEnum):
    ANALYZING = "ANALYZING"
    AI_PENDING = "AI_PENDING"
    NEW = "NEW"
    TAKEN = "TAKEN"
    CONTACTED = "CONTACTED"
    QUALIFIED = "QUALIFIED"
    OFFER_SENT = "OFFER_SENT"
    NEGOTIATION = "NEGOTIATION"
    WON = "WON"
    LOST = "LOST"
    NOT_LEAD = "NOT_LEAD"


class DealStatus(StrEnum):
    NEW = "NEW"
    QUALIFIED = "QUALIFIED"
    OFFER_SENT = "OFFER_SENT"
    NEGOTIATION = "NEGOTIATION"
    WON = "WON"
    LOST = "LOST"


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"


class NotificationPolicy(StrEnum):
    ALL_NEW_COMMENTS = "ALL_NEW_COMMENTS"
    COMMERCIAL_ONLY = "COMMERCIAL_ONLY"
    HOT_ONLY = "HOT_ONLY"


class PublicSignalStatus(StrEnum):
    ANALYZING = "ANALYZING"
    ANALYZED = "ANALYZED"
    FAILED = "FAILED"


class CoverageStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    LATEST_ONLY = "LATEST_ONLY"


class MonitorRunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class TaskStatus(StrEnum):
    OPEN = "OPEN"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class Competitor(Base):
    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), default="instagram")
    handle: Mapped[str] = mapped_column(String(255))
    normalized_handle: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(64), default="DIRECT")
    tier: Mapped[str] = mapped_column(String(8), default="A", index=True)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=180)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notification_policy: Mapped[NotificationPolicy | None] = mapped_column(
        Enum(NotificationPolicy, native_enum=False), index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(Text)
    catalog_managed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scan_error_count: Mapped[int] = mapped_column(Integer, default=0)
    baseline_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    baseline_provider: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    posts: Mapped[list[Post]] = relationship(back_populates="competitor")


class MarketCandidate(Base):
    __tablename__ = "market_candidates"
    __table_args__ = (
        UniqueConstraint("display_name", name="uq_market_candidates_display_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    instagram_handle: Mapped[str | None] = mapped_column(String(255), index=True)
    website_url: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), default="DIRECT", index=True)
    tier: Mapped[str] = mapped_column(String(8), default="B", index=True)
    confidence: Mapped[int] = mapped_column(Integer, default=50)
    rationale: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="DISCOVERED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("platform", "platform_post_id"),
        UniqueConstraint("platform", "url", name="uq_posts_platform_url"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), default="instagram")
    platform_post_id: Mapped[str] = mapped_column(String(255))
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    caption: Mapped[str] = mapped_column(Text, default="")
    post_type: Mapped[str] = mapped_column(String(32), default="REEL")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comments_count: Mapped[int] = mapped_column(Integer, default=0)
    # Number of comments actually returned by the provider during the last successful fetch.
    comments_fetched_count: Mapped[int | None] = mapped_column(Integer)
    # Remote comments_count value for which a fetch was successfully completed.
    last_synced_remote_count: Mapped[int | None] = mapped_column(Integer)
    comment_pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    coverage_status: Mapped[CoverageStatus] = mapped_column(
        Enum(CoverageStatus, native_enum=False), default=CoverageStatus.UNKNOWN, index=True
    )
    last_comment_provider: Mapped[str | None] = mapped_column(String(128))
    comments_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    competitor: Mapped[Competitor] = relationship(back_populates="posts")
    comments: Mapped[list[Comment]] = relationship(back_populates="post")


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint(
            "platform", "platform_user_id", name="uq_contacts_platform_user_id"
        ),
        UniqueConstraint(
            "platform", "normalized_username", name="uq_contacts_platform_username"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), default="instagram")
    platform_user_id: Mapped[str | None] = mapped_column(String(255), index=True)
    username: Mapped[str] = mapped_column(String(255))
    normalized_username: Mapped[str] = mapped_column(String(255), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    profile_url: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    current_lead_score: Mapped[int] = mapped_column(Integer, default=0)
    assigned_manager_telegram_id: Mapped[int | None] = mapped_column()
    phone: Mapped[str | None] = mapped_column(String(64))
    preferred_channel: Mapped[str | None] = mapped_column(String(32))
    city: Mapped[str | None] = mapped_column(String(128))
    interest_summary: Mapped[str | None] = mapped_column(String(255))
    desired_quantity: Mapped[int | None] = mapped_column(Integer)
    budget_from: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    budget_to: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    desired_color: Mapped[str | None] = mapped_column(String(128))
    purchase_timeline: Mapped[str | None] = mapped_column(String(128))
    qualification_note: Mapped[str | None] = mapped_column(Text)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    qualification_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    comments: Mapped[list[Comment]] = relationship(back_populates="contact")
    events: Mapped[list[ContactEvent]] = relationship(back_populates="contact")
    leads: Mapped[list[Lead]] = relationship(back_populates="contact")


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (
        UniqueConstraint(
            "platform", "platform_comment_id", name="uq_comments_platform_comment_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), default="instagram")
    platform_comment_id: Mapped[str] = mapped_column(String(255))
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at_platform: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    contact: Mapped[Contact] = relationship(back_populates="comments")
    post: Mapped[Post] = relationship(back_populates="comments")
    lead: Mapped[Lead | None] = relationship(back_populates="comment")
    public_signal: Mapped[PublicSignal | None] = relationship(back_populates="comment")


class PublicSignal(Base):
    __tablename__ = "public_signals"
    __table_args__ = (
        UniqueConstraint("comment_id", name="uq_public_signals_comment_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), index=True)
    status: Mapped[PublicSignalStatus] = mapped_column(
        Enum(PublicSignalStatus, native_enum=False),
        default=PublicSignalStatus.ANALYZING,
        index=True,
    )
    pipeline_stage: Mapped[str] = mapped_column(String(64), default="PERSISTED")
    error: Mapped[str | None] = mapped_column(Text)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    comment: Mapped[Comment] = relationship(back_populates="public_signal")


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), unique=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), index=True)
    intent: Mapped[str] = mapped_column(String(64), default="OTHER")
    product_category: Mapped[str | None] = mapped_column(String(128))
    lead_score: Mapped[int] = mapped_column(Integer, default=0)
    ai_reason: Mapped[str] = mapped_column(Text, default="")
    analysis_details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    language: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, native_enum=False), default=LeadStatus.AI_PENDING, index=True
    )
    assigned_manager_telegram_id: Mapped[int | None] = mapped_column()
    ai_source: Mapped[str | None] = mapped_column(String(32))
    ai_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    next_action_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    contact: Mapped[Contact] = relationship(back_populates="leads")
    comment: Mapped[Comment] = relationship(back_populates="lead")
    deals: Mapped[list[Deal]] = relationship(back_populates="lead")
    feedback: Mapped[AIFeedback | None] = relationship(back_populates="lead")


class Deal(Base):
    __tablename__ = "deals"
    __table_args__ = (
        UniqueConstraint("lead_id", name="uq_deals_lead_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), index=True)
    manager_telegram_id: Mapped[int | None] = mapped_column()
    status: Mapped[DealStatus] = mapped_column(
        Enum(DealStatus, native_enum=False), default=DealStatus.NEW, index=True
    )
    product_name: Mapped[str | None] = mapped_column(String(255))
    product_category: Mapped[str | None] = mapped_column(String(128))
    quantity: Mapped[int | None] = mapped_column(Integer)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    discount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    final_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    lost_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    won_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lost_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lead: Mapped[Lead | None] = relationship(back_populates="deals")


class ContactEvent(Base):
    __tablename__ = "contact_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    event_type: Mapped[ContactEventType] = mapped_column(
        Enum(ContactEventType, native_enum=False), index=True
    )
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), index=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id"), index=True)
    manager_telegram_id: Mapped[int | None] = mapped_column()
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    contact: Mapped[Contact] = relationship(back_populates="events")


class AIFeedback(Base):
    __tablename__ = "ai_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), unique=True)
    comment_text: Mapped[str] = mapped_column(Text)
    post_context: Mapped[str] = mapped_column(Text)
    predicted_intent: Mapped[str] = mapped_column(String(64))
    predicted_product: Mapped[str | None] = mapped_column(String(128))
    predicted_score: Mapped[int] = mapped_column(Integer)
    manager_is_lead: Mapped[bool | None] = mapped_column(Boolean)
    actual_outcome: Mapped[str | None] = mapped_column(String(64))
    deal_created: Mapped[bool] = mapped_column(Boolean, default=False)
    deal_won: Mapped[bool] = mapped_column(Boolean, default=False)
    deal_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    lost_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    lead: Mapped[Lead] = relationship(back_populates="feedback")


class NotificationLog(Base):
    __tablename__ = "notification_logs"
    __table_args__ = (
        UniqueConstraint("lead_id", "chat_id", name="uq_notification_logs_lead_chat"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    chat_id: Mapped[int] = mapped_column(index=True)
    message_id: Mapped[int | None] = mapped_column()
    content_version: Mapped[int] = mapped_column(Integer, default=1)
    enrichment_followup_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, native_enum=False), default=NotificationStatus.PENDING
    )
    error: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MonitorRun(Base):
    __tablename__ = "monitor_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(64), default="schedule", index=True)
    provider: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[MonitorRunStatus] = mapped_column(
        Enum(MonitorRunStatus, native_enum=False),
        default=MonitorRunStatus.RUNNING,
        index=True,
    )
    stats_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContactTask(Base):
    __tablename__ = "contact_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), index=True)
    manager_telegram_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False, length=16), default=TaskStatus.OPEN, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AnalysisCache(Base):
    __tablename__ = "analysis_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    model: Mapped[str] = mapped_column(String(128))
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExternalUsage(Base):
    __tablename__ = "external_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str] = mapped_column(String(64), index=True)
    operation: Mapped[str] = mapped_column(String(128), index=True)
    units: Mapped[int] = mapped_column(Integer, default=1)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
