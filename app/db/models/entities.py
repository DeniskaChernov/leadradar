from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
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
    SIGNIFICANT_CHANGE = "SIGNIFICANT_CHANGE"
    CONTACT_IDENTITY_CHANGED = "CONTACT_IDENTITY_CHANGED"


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
    UNCERTAIN = "UNCERTAIN"


class NotificationPolicy(StrEnum):
    ALL_NEW_COMMENTS = "ALL_NEW_COMMENTS"
    COMMERCIAL_ONLY = "COMMERCIAL_ONLY"
    HOT_ONLY = "HOT_ONLY"


class PublicSignalStatus(StrEnum):
    ANALYZING = "ANALYZING"
    ANALYZED = "ANALYZED"
    FAILED = "FAILED"


class ExportEligibility(StrEnum):
    NOT_EXPORTABLE = "NOT_EXPORTABLE"
    FIRST_PARTY_ELIGIBLE = "FIRST_PARTY_ELIGIBLE"
    EXPORTED = "EXPORTED"


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


class AIRequestStatus(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRYABLE = "RETRYABLE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"


class ReservationStatus(StrEnum):
    RESERVED = "RESERVED"
    FINALIZED = "FINALIZED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    UNCERTAIN = "UNCERTAIN"


class Vertical(StrEnum):
    FURNITURE = "FURNITURE"
    ARTIFICIAL_RATTAN = "ARTIFICIAL_RATTAN"


class SignalSubjectType(StrEnum):
    CONTACT = "CONTACT"
    BUSINESS = "BUSINESS"
    UNKNOWN = "UNKNOWN"


class SignalType(StrEnum):
    COMMENT = "COMMENT"
    POST = "POST"
    REEL = "REEL"
    PROFILE = "PROFILE"
    TAGGED_POST = "TAGGED_POST"
    FOLLOWER_RELATION = "FOLLOWER_RELATION"
    FOLLOWING_RELATION = "FOLLOWING_RELATION"
    MARKETPLACE_LISTING = "MARKETPLACE_LISTING"
    PRODUCT_PAGE = "PRODUCT_PAGE"
    WEBSITE_MENTION = "WEBSITE_MENTION"
    GOOGLE_PLACE_DISCOVERY = "GOOGLE_PLACE_DISCOVERY"
    BUSINESS_OPENING = "BUSINESS_OPENING"
    GOOGLE_REVIEW_REFERENCE = "GOOGLE_REVIEW_REFERENCE"
    PRICE_MENTION = "PRICE_MENTION"
    PRICE_CHANGE = "PRICE_CHANGE"
    STOCK_MENTION = "STOCK_MENTION"
    NEW_ARRIVAL = "NEW_ARRIVAL"
    SEARCH_RESULT = "SEARCH_RESULT"
    MANAGER_INPUT = "MANAGER_INPUT"
    FIRST_PARTY_ACTION = "FIRST_PARTY_ACTION"
    OTHER = "OTHER"


class BusinessAliasType(StrEnum):
    DOMAIN = "DOMAIN"
    BRAND_NAME = "BRAND_NAME"
    LEGAL_NAME = "LEGAL_NAME"
    INSTAGRAM_HANDLE = "INSTAGRAM_HANDLE"
    GOOGLE_PLACE_ID = "GOOGLE_PLACE_ID"
    PUBLIC_PHONE = "PUBLIC_PHONE"
    MARKETPLACE_SELLER_ID = "MARKETPLACE_SELLER_ID"
    PUBLIC_TELEGRAM = "PUBLIC_TELEGRAM"
    OTHER = "OTHER"


class BusinessEntityStatus(StrEnum):
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
    VERIFIED = "VERIFIED"
    MERGED = "MERGED"
    ARCHIVED = "ARCHIVED"


class BusinessEntity(Base):
    __tablename__ = "business_entities"
    __table_args__ = (
        UniqueConstraint("canonical_key", name="uq_business_entities_canonical_key"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_business_entities_confidence",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_key: Mapped[str] = mapped_column(String(255), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    verticals_json: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: [Vertical.FURNITURE.value]
    )
    country: Mapped[str | None] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(128))
    website_url: Mapped[str | None] = mapped_column(Text)
    instagram_handle: Mapped[str | None] = mapped_column(String(255), index=True)
    primary_role: Mapped[str | None] = mapped_column(String(64), index=True)
    entity_status: Mapped[BusinessEntityStatus] = mapped_column(
        Enum(BusinessEntityStatus, native_enum=False),
        default=BusinessEntityStatus.NEEDS_VERIFICATION,
        index=True,
    )
    confidence: Mapped[int] = mapped_column(Integer, default=50)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    aliases: Mapped[list[BusinessAlias]] = relationship(back_populates="business")


class BusinessAlias(Base):
    __tablename__ = "business_aliases"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "alias_type",
            "normalized_value",
            name="uq_business_aliases_business_type_value",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_business_aliases_confidence",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("business_entities.id"), index=True)
    alias_type: Mapped[BusinessAliasType] = mapped_column(
        Enum(BusinessAliasType, native_enum=False), index=True
    )
    value: Mapped[str] = mapped_column(String(512))
    normalized_value: Mapped[str] = mapped_column(String(512), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidence.id"), index=True)
    confidence: Mapped[int] = mapped_column(Integer, default=50)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    business: Mapped[BusinessEntity] = relationship(back_populates="aliases")


class Competitor(Base):
    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_entities.id"), unique=True, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), default="instagram")
    handle: Mapped[str] = mapped_column(String(255))
    normalized_handle: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    vertical: Mapped[Vertical] = mapped_column(
        Enum(Vertical, native_enum=False), default=Vertical.FURNITURE, index=True
    )
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
    __table_args__ = (UniqueConstraint("display_name", name="uq_market_candidates_display_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    canonical_key: Mapped[str | None] = mapped_column(String(512), unique=True, index=True)
    vertical: Mapped[Vertical] = mapped_column(
        Enum(Vertical, native_enum=False), default=Vertical.FURNITURE, index=True
    )
    contact_hint: Mapped[str | None] = mapped_column(String(255))
    instagram_handle: Mapped[str | None] = mapped_column(String(255), index=True)
    website_url: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), default="DIRECT", index=True)
    tier: Mapped[str] = mapped_column(String(8), default="B", index=True)
    confidence: Mapped[int] = mapped_column(Integer, default=50)
    rationale: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64), default="MANUAL", index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255))
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    snapshot_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="DISCOVERED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MarketCandidateDiff(Base):
    __tablename__ = "market_candidate_diffs"
    __table_args__ = (
        UniqueConstraint("candidate_id", "snapshot_fingerprint", name="uq_candidate_diff_snapshot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("market_candidates.id"), index=True)
    diff_type: Mapped[str] = mapped_column(String(32), default="UPDATED", index=True)
    changed_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    before_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    snapshot_fingerprint: Mapped[str] = mapped_column(String(64))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("canonical_key", name="uq_products_canonical_key"),
        UniqueConstraint("sku", name="uq_products_sku"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    sku: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    vertical: Mapped[Vertical] = mapped_column(
        Enum(Vertical, native_enum=False, length=32),
        default=Vertical.FURNITURE,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(64), default="UNCONFIRMED", index=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    cogs: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    stock: Mapped[int | None] = mapped_column(Integer)
    minimum_order_quantity: Mapped[int | None] = mapped_column(Integer)
    dimensions_json: Mapped[dict[str, float] | None] = mapped_column(JSON)
    colors_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_load_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    b2b_suitability: Mapped[str] = mapped_column(String(32), default="UNCONFIRMED")
    photo_url: Mapped[str | None] = mapped_column(Text)
    source_reference: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
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
        UniqueConstraint("platform", "platform_user_id", name="uq_contacts_platform_user_id"),
        UniqueConstraint("platform", "normalized_username", name="uq_contacts_platform_username"),
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
    intelligence: Mapped[ContactIntelligence | None] = relationship(back_populates="contact")


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (
        UniqueConstraint("platform", "platform_comment_id", name="uq_comments_platform_comment_id"),
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
        UniqueConstraint(
            "platform",
            "signal_type",
            "external_id",
            name="uq_public_signals_external_identity",
        ),
        CheckConstraint(
            "source_quality_score >= 0 AND source_quality_score <= 100",
            name="ck_public_signals_source_quality_score",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_public_signals_confidence",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), index=True)
    vertical: Mapped[Vertical] = mapped_column(
        Enum(Vertical, native_enum=False), default=Vertical.FURNITURE, index=True
    )
    subject_type: Mapped[SignalSubjectType] = mapped_column(
        Enum(SignalSubjectType, native_enum=False),
        default=SignalSubjectType.CONTACT,
        index=True,
    )
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"), index=True)
    business_id: Mapped[int | None] = mapped_column(ForeignKey("business_entities.id"), index=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), index=True)
    platform: Mapped[str] = mapped_column(String(32), default="instagram", index=True)
    signal_type: Mapped[SignalType] = mapped_column(
        Enum(SignalType, native_enum=False), default=SignalType.COMMENT, index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(255))
    dedupe_key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_account: Mapped[str | None] = mapped_column(String(255), index=True)
    source_competitor_id: Mapped[int | None] = mapped_column(
        ForeignKey("competitors.id"), index=True
    )
    text: Mapped[str | None] = mapped_column(Text)
    payload_summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    source_quality_score: Mapped[int] = mapped_column(Integer, default=70)
    confidence: Mapped[int] = mapped_column(Integer, default=100)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
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
    evidence: Mapped[list[Evidence]] = relationship(back_populates="public_signal")


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint("evidence_key", name="uq_evidence_evidence_key"),
        CheckConstraint("strength >= 0 AND strength <= 100", name="ck_evidence_strength"),
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_evidence_confidence"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_key: Mapped[str] = mapped_column(String(512), index=True)
    public_signal_id: Mapped[int] = mapped_column(ForeignKey("public_signals.id"), index=True)
    vertical: Mapped[Vertical] = mapped_column(
        Enum(Vertical, native_enum=False), default=Vertical.FURNITURE, index=True
    )
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(String(128), index=True)
    intent: Mapped[str | None] = mapped_column(String(64), index=True)
    strength: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[int] = mapped_column(Integer, default=100)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    public_signal: Mapped[PublicSignal] = relationship(back_populates="evidence")


class InterestEvidence(Base):
    """A commercial interest observation derived from one persisted Evidence row."""

    __tablename__ = "interest_evidence"
    __table_args__ = (
        UniqueConstraint("interest_key", name="uq_interest_evidence_interest_key"),
        CheckConstraint("strength >= 0 AND strength <= 100", name="ck_interest_evidence_strength"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_interest_evidence_confidence",
        ),
        CheckConstraint("half_life_days > 0", name="ck_interest_evidence_half_life_days"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    interest_key: Mapped[str] = mapped_column(String(512), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    public_signal_id: Mapped[int] = mapped_column(ForeignKey("public_signals.id"), index=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.id"), index=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), index=True)
    vertical: Mapped[str] = mapped_column(String(64), default="FURNITURE", index=True)
    dimension: Mapped[str] = mapped_column(String(32), index=True)
    topic: Mapped[str] = mapped_column(String(128), index=True)
    strength: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[int] = mapped_column(Integer)
    half_life_days: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ContactInterestProfile(Base):
    """Current decayed score for one observable commercial topic."""

    __tablename__ = "contact_interest_profiles"
    __table_args__ = (
        UniqueConstraint(
            "contact_id",
            "vertical",
            "dimension",
            "topic",
            name="uq_contact_interest_profiles_scope",
        ),
        CheckConstraint(
            "current_score >= 0 AND current_score <= 100",
            name="ck_contact_interest_profiles_current_score",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_contact_interest_profiles_confidence",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    vertical: Mapped[str] = mapped_column(String(64), default="FURNITURE", index=True)
    dimension: Mapped[str] = mapped_column(String(32), index=True)
    topic: Mapped[str] = mapped_column(String(128), index=True)
    current_score: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    commercial_signal_count: Mapped[int] = mapped_column(Integer, default=0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    competitor_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence_ids_json: Mapped[list[int]] = mapped_column(JSON, default=list)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class OutcomeDNA(Base):
    """Immutable feature snapshot observed before a deal was won."""

    __tablename__ = "outcome_dna"
    __table_args__ = (UniqueConstraint("deal_id", name="uq_outcome_dna_deal_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    vertical: Mapped[str] = mapped_column(String(64), default="FURNITURE", index=True)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    product_topics_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    intents_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    buyer_role: Mapped[str] = mapped_column(String(32), default="UNKNOWN", index=True)
    quantity_band: Mapped[str | None] = mapped_column(String(32))
    commercial_stage: Mapped[str] = mapped_column(String(64), default="NON_COMMERCIAL")
    commercial_signal_count: Mapped[int] = mapped_column(Integer, default=0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    competitor_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence_ids_json: Mapped[list[int]] = mapped_column(JSON, default=list)
    engine_version: Mapped[str] = mapped_column(String(32), default="3.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ContactIntelligence(Base):
    __tablename__ = "contact_intelligence"
    __table_args__ = (UniqueConstraint("contact_id", name="uq_contact_intelligence_contact_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    vertical: Mapped[str] = mapped_column(String(64), default="FURNITURE")
    commercial_stage: Mapped[str] = mapped_column(String(64), default="NON_COMMERCIAL")
    intent_strength: Mapped[int] = mapped_column(Integer, default=0)
    signal_count: Mapped[int] = mapped_column(Integer, default=0)
    commercial_signal_count: Mapped[int] = mapped_column(Integer, default=0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    competitor_count: Mapped[int] = mapped_column(Integer, default=0)
    activity_score: Mapped[int] = mapped_column(Integer, default=0)
    value_score: Mapped[int] = mapped_column(Integer, default=0)
    fit_score: Mapped[int] = mapped_column(Integer, default=0)
    customer_type: Mapped[str] = mapped_column(String(16), default="B2C")
    quantity_band: Mapped[str | None] = mapped_column(String(32))
    purchase_horizon: Mapped[str | None] = mapped_column(String(32))
    product_interests_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    top_intents_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    export_eligibility: Mapped[ExportEligibility] = mapped_column(
        Enum(ExportEligibility, native_enum=False),
        default=ExportEligibility.NOT_EXPORTABLE,
        index=True,
    )
    # Phase 4 — Profile DNA fields
    primary_buyer_role: Mapped[str] = mapped_column(String(32), default="UNKNOWN", index=True)
    buyer_roles_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    similarity_vector_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    contact: Mapped[Contact] = relationship(back_populates="intelligence")


class AudienceSegment(Base):
    __tablename__ = "audience_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    vertical: Mapped[Vertical] = mapped_column(
        Enum(Vertical, native_enum=False), default=Vertical.FURNITURE, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    audience_family: Mapped[str] = mapped_column(String(32), default="INTENT", index=True)
    audience_level: Mapped[str] = mapped_column(String(32), default="CORE", index=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    membership_strategy: Mapped[str] = mapped_column(String(32), default="RULE")
    minimum_evidence_count: Mapped[int] = mapped_column(Integer, default=1)
    minimum_confidence: Mapped[int] = mapped_column(Integer, default=50)
    minimum_current_score: Mapped[int] = mapped_column(Integer, default=20)
    recency_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    decay_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    criteria_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    meta_use_case: Mapped[str] = mapped_column(String(32), default="ANALYSIS_ONLY", index=True)
    created_by: Mapped[str] = mapped_column(String(64), default="SYSTEM_REGISTRY")
    engine_version: Mapped[str] = mapped_column(String(32), default="4.0")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AudienceMembership(Base):
    __tablename__ = "audience_memberships"
    __table_args__ = (
        UniqueConstraint(
            "segment_id", "contact_id", name="uq_audience_memberships_segment_contact"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("audience_segments.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    reasons_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    evidence_ids_json: Mapped[list[int]] = mapped_column(JSON, default=list)
    engine_version: Mapped[str] = mapped_column(String(32), default="3.0")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MetaAudienceBlueprint(Base):
    """Activation plan for an internal audience; never an external Meta audience ID."""

    __tablename__ = "meta_audience_blueprints"
    __table_args__ = (
        UniqueConstraint(
            "audience_definition_id", "mode", name="uq_meta_blueprint_definition_mode"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    audience_definition_id: Mapped[int] = mapped_column(
        ForeignKey("audience_segments.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    purpose: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(32), default="ANALYSIS_ONLY", index=True)
    eligibility_status: Mapped[str] = mapped_column(String(32), default="NOT_CONNECTED", index=True)
    reason: Mapped[str] = mapped_column(Text)
    first_party_required: Mapped[bool] = mapped_column(Boolean, default=False)
    minimum_seed_size: Mapped[int] = mapped_column(Integer, default=0)
    data_requirements_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    suggested_geo_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    suggested_interests_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    suggested_exclusions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    suggested_broadness: Mapped[str] = mapped_column(String(16), default="BROAD")
    meta_catalog_version: Mapped[str | None] = mapped_column(String(64))
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    engine_version: Mapped[str] = mapped_column(String(32), default="4.1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MetaInterest(Base):
    __tablename__ = "meta_interests"
    __table_args__ = (
        UniqueConstraint(
            "meta_interest_id",
            name="uq_meta_interests_meta_interest_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    meta_interest_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    path_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    audience_size: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MetaInterestMapping(Base):
    __tablename__ = "meta_interest_mappings"
    __table_args__ = (
        UniqueConstraint(
            "internal_topic",
            "meta_interest_id",
            "mapping_version",
            name="uq_meta_interest_mapping_scope",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    internal_topic: Mapped[str] = mapped_column(String(128), index=True)
    meta_interest_id: Mapped[str] = mapped_column(
        ForeignKey("meta_interests.meta_interest_id"), index=True
    )
    mapping_score: Mapped[int] = mapped_column(Integer, default=0)
    mapping_reason: Mapped[str] = mapped_column(Text)
    mapping_version: Mapped[str] = mapped_column(String(32), default="1.0")
    validated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MetaTargetingRecipe(Base):
    __tablename__ = "meta_targeting_recipes"
    __table_args__ = (
        UniqueConstraint(
            "blueprint_id", "strategy", "version", name="uq_meta_targeting_recipe_version"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    blueprint_id: Mapped[int] = mapped_column(ForeignKey("meta_audience_blueprints.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    objective: Mapped[str] = mapped_column(String(64), default="ANALYSIS_ONLY")
    strategy: Mapped[str] = mapped_column(String(16), index=True)
    geo_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    age_policy: Mapped[str] = mapped_column(String(64), default="BROAD_UNLESS_JUSTIFIED")
    interest_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    excluded_interest_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    custom_audience_inclusions_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    custom_audience_exclusions_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    lookalike_seed: Mapped[str | None] = mapped_column(String(255))
    broad_targeting: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="NOT_CONNECTED", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MetaExportCandidate(Base):
    __tablename__ = "meta_export_candidates"
    __table_args__ = (
        UniqueConstraint(
            "blueprint_id", "contact_id", name="uq_meta_export_candidate_blueprint_contact"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    blueprint_id: Mapped[int] = mapped_column(ForeignKey("meta_audience_blueprints.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    eligibility_status: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    evidence_ids_json: Mapped[list[int]] = mapped_column(JSON, default=list)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MetaAudienceSync(Base):
    __tablename__ = "meta_audience_syncs"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_meta_audience_syncs_idempotency_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    blueprint_id: Mapped[int] = mapped_column(ForeignKey("meta_audience_blueprints.id"), index=True)
    external_audience_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="NOT_CONNECTED", index=True)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SignificantChange(Base):
    __tablename__ = "significant_changes"
    __table_args__ = (UniqueConstraint("lead_id", name="uq_significant_changes_lead_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    primary_type: Mapped[str] = mapped_column(String(64), index=True)
    change_types_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM", index=True)
    previous_priority: Mapped[int] = mapped_column(Integer, default=0)
    current_priority: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text)
    before_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    after_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class SignificantChangeNotification(Base):
    __tablename__ = "significant_change_notifications"
    __table_args__ = (
        UniqueConstraint("change_id", "chat_id", name="uq_significant_change_notifications_target"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("significant_changes.id"), index=True)
    chat_id: Mapped[int] = mapped_column(index=True)
    message_id: Mapped[int | None] = mapped_column()
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, native_enum=False), default=NotificationStatus.PENDING, index=True
    )
    error: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(128), index=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    delivery_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uncertain_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), unique=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), index=True)
    vertical: Mapped[Vertical] = mapped_column(
        Enum(Vertical, native_enum=False), default=Vertical.FURNITURE, index=True
    )
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
    __table_args__ = (UniqueConstraint("lead_id", name="uq_deals_lead_id"),)

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
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    chat_id: Mapped[int] = mapped_column(index=True)
    message_id: Mapped[int | None] = mapped_column()
    content_version: Mapped[int] = mapped_column(Integer, default=1)
    enrichment_followup_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrichment_followup_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, native_enum=False), default=NotificationStatus.PENDING
    )
    error: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(128), index=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    delivery_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uncertain_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(String(64))
    edit_claim_token: Mapped[str | None] = mapped_column(String(64), index=True)
    edit_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    edit_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
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
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
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
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    service: Mapped[str] = mapped_column(String(64), index=True)
    operation: Mapped[str] = mapped_column(String(128), index=True)
    units: Mapped[int] = mapped_column(Integer, default=1)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class OpeningSignal(Base):
    __tablename__ = "opening_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    place_name: Mapped[str] = mapped_column(String(255), index=True)
    place_type: Mapped[str] = mapped_column(String(64), default="OTHER")
    city: Mapped[str] = mapped_column(String(128), default="Tashkent")
    address: Mapped[str | None] = mapped_column(Text)
    opening_timeline: Mapped[str | None] = mapped_column(String(128))
    google_place_id: Mapped[str | None] = mapped_column(String(255))
    confidence: Mapped[int] = mapped_column(Integer, default=50)
    source_type: Mapped[str] = mapped_column(String(64), default="INSTAGRAM_PUBLIC_SIGNAL")
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"), index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    review_status: Mapped[str] = mapped_column(String(32), default="PENDING_REVIEW", index=True)
    reviewed_by_manager_id: Mapped[int | None] = mapped_column(Integer)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIRequest(Base):
    __tablename__ = "ai_requests"
    __table_args__ = (
        UniqueConstraint(
            "lead_id",
            "analysis_version",
            "context_fingerprint",
            name="uq_ai_requests_lead_version_fingerprint",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    analysis_version: Mapped[str] = mapped_column(String(32), default="3.0", index=True)
    prompt_version: Mapped[str] = mapped_column(String(32), default="lead-v3")
    schema_version: Mapped[str] = mapped_column(String(32), default="lead-analysis-v3")
    context_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(128))
    status: Mapped[AIRequestStatus] = mapped_column(
        Enum(AIRequestStatus, native_enum=False), default=AIRequestStatus.PENDING, index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), index=True)
    claim_token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.000000"))
    actual_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    response_cache_key: Mapped[str | None] = mapped_column(String(64), index=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ExternalBudgetReservation(Base):
    __tablename__ = "external_budget_reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    reservation_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), index=True)
    service: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(128), index=True)
    operation: Mapped[str] = mapped_column(String(128), index=True)
    units_reserved: Mapped[int] = mapped_column(Integer, default=1)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0.000000"))
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[ReservationStatus] = mapped_column(
        Enum(ReservationStatus, native_enum=False), default=ReservationStatus.RESERVED, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reserved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    call_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_units: Mapped[int | None] = mapped_column(Integer)
    actual_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CostEvent(Base):
    __tablename__ = "cost_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    reservation_id: Mapped[int | None] = mapped_column(
        ForeignKey("external_budget_reservations.id"), unique=True, index=True
    )
    service: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(128), index=True)
    operation: Mapped[str] = mapped_column(String(128), index=True)
    vertical: Mapped[Vertical | None] = mapped_column(Enum(Vertical, native_enum=False), index=True)
    competitor_id: Mapped[int | None] = mapped_column(ForeignKey("competitors.id"), index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), index=True)
    audience_id: Mapped[int | None] = mapped_column(ForeignKey("audience_segments.id"), index=True)
    campaign_id: Mapped[int | None] = mapped_column(Integer, index=True)
    units: Mapped[int] = mapped_column(Integer, default=1)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class PricingConfig(Base):
    __tablename__ = "pricing_configs"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "operation",
            "model_name",
            "effective_from",
            name="uq_pricing_configs_provider_operation_model_effective",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(128), index=True)
    operation: Mapped[str] = mapped_column(String(128), index=True)
    model_name: Mapped[str] = mapped_column(String(128), default="", index=True)
    pricing_basis: Mapped[str] = mapped_column(String(32))
    input_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 8))
    output_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 8))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 8))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
