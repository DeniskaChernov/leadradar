"""add V4 universal signal and business identity foundation

Revision ID: 4b1f6a9c2d70
Revises: c93a1f7d2e40
Create Date: 2026-08-27 18:30:00
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "4b1f6a9c2d70"
down_revision: str | Sequence[str] | None = "c93a1f7d2e40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


vertical = sa.Enum(
    "FURNITURE", "ARTIFICIAL_RATTAN", name="vertical", native_enum=False
)
subject_type = sa.Enum(
    "CONTACT", "BUSINESS", "UNKNOWN", name="signalsubjecttype", native_enum=False
)
signal_type = sa.Enum(
    "COMMENT",
    "POST",
    "REEL",
    "PROFILE",
    "TAGGED_POST",
    "FOLLOWER_RELATION",
    "FOLLOWING_RELATION",
    "MARKETPLACE_LISTING",
    "PRODUCT_PAGE",
    "WEBSITE_MENTION",
    "GOOGLE_PLACE_DISCOVERY",
    "BUSINESS_OPENING",
    "GOOGLE_REVIEW_REFERENCE",
    "PRICE_MENTION",
    "PRICE_CHANGE",
    "STOCK_MENTION",
    "NEW_ARRIVAL",
    "SEARCH_RESULT",
    "MANAGER_INPUT",
    "FIRST_PARTY_ACTION",
    "OTHER",
    name="signaltype",
    native_enum=False,
)
business_status = sa.Enum(
    "NEEDS_VERIFICATION",
    "VERIFIED",
    "MERGED",
    "ARCHIVED",
    name="businessentitystatus",
    native_enum=False,
)
alias_type = sa.Enum(
    "DOMAIN",
    "BRAND_NAME",
    "LEGAL_NAME",
    "INSTAGRAM_HANDLE",
    "GOOGLE_PLACE_ID",
    "PUBLIC_PHONE",
    "MARKETPLACE_SELLER_ID",
    "PUBLIC_TELEGRAM",
    "OTHER",
    name="businessaliastype",
    native_enum=False,
)
contact_event_type = sa.Enum(
    "COMMENT_FOUND",
    "LEAD_CREATED",
    "LEAD_SCORE_CHANGED",
    "MANAGER_ASSIGNED",
    "MANAGER_MARKED_NOT_LEAD",
    "CONTACTED",
    "CUSTOMER_REPLIED",
    "NOTE_ADDED",
    "PRODUCT_INTEREST_ADDED",
    "OFFER_SENT",
    "NEGOTIATION_STARTED",
    "DEAL_CREATED",
    "DEAL_WON",
    "DEAL_LOST",
    "LEAD_STATUS_CHANGED",
    "NEXT_CONTACT_SCHEDULED",
    "NEXT_CONTACT_COMPLETED",
    "NEXT_CONTACT_CANCELLED",
    "QUALIFICATION_UPDATED",
    "LEAD_REOPENED",
    "SIGNIFICANT_CHANGE",
    "CONTACT_IDENTITY_CHANGED",
    name="contacteventtype",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "business_entities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("canonical_key", sa.String(length=255), nullable=False),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("verticals_json", sa.JSON(), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("instagram_handle", sa.String(length=255), nullable=True),
        sa.Column("primary_role", sa.String(length=64), nullable=True),
        sa.Column(
            "entity_status",
            business_status,
            nullable=False,
            server_default="NEEDS_VERIFICATION",
        ),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_business_entities_confidence",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_key", name="uq_business_entities_canonical_key"),
    )
    op.create_index(
        "ix_business_entities_canonical_key", "business_entities", ["canonical_key"]
    )
    op.create_index(
        "ix_business_entities_normalized_name", "business_entities", ["normalized_name"]
    )
    op.create_index(
        "ix_business_entities_instagram_handle", "business_entities", ["instagram_handle"]
    )
    op.create_index(
        "ix_business_entities_primary_role", "business_entities", ["primary_role"]
    )
    op.create_index(
        "ix_business_entities_entity_status", "business_entities", ["entity_status"]
    )

    with op.batch_alter_table("competitors") as batch:
        batch.add_column(sa.Column("business_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_competitors_business_id_business_entities",
            "business_entities",
            ["business_id"],
            ["id"],
        )
        batch.create_index("ix_competitors_business_id", ["business_id"], unique=True)

    with op.batch_alter_table("market_candidates") as batch:
        batch.add_column(
            sa.Column("vertical", vertical, nullable=False, server_default="FURNITURE")
        )
        batch.add_column(sa.Column("contact_hint", sa.String(length=255), nullable=True))
        batch.create_index("ix_market_candidates_vertical", ["vertical"])

    with op.batch_alter_table("contact_events") as batch:
        batch.alter_column(
            "event_type",
            existing_type=sa.String(length=23),
            type_=contact_event_type,
            existing_nullable=False,
        )

    with op.batch_alter_table("public_signals") as batch:
        batch.add_column(
            sa.Column("vertical", vertical, nullable=False, server_default="FURNITURE")
        )
        batch.add_column(
            sa.Column("subject_type", subject_type, nullable=False, server_default="CONTACT")
        )
        batch.add_column(sa.Column("business_id", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("platform", sa.String(length=32), nullable=False, server_default="instagram")
        )
        batch.add_column(
            sa.Column("signal_type", signal_type, nullable=False, server_default="COMMENT")
        )
        batch.add_column(sa.Column("external_id", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("dedupe_key", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("source_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("source_account", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("source_competitor_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("payload_summary", sa.Text(), nullable=True))
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column(
                "discovered_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
        batch.add_column(
            sa.Column("source_quality_score", sa.Integer(), nullable=False, server_default="70")
        )
        batch.add_column(
            sa.Column("confidence", sa.Integer(), nullable=False, server_default="100")
        )
        batch.add_column(
            sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("raw_data", sa.JSON(), nullable=True))
        batch.create_foreign_key(
            "fk_public_signals_business_id_business_entities",
            "business_entities",
            ["business_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_public_signals_source_competitor_id_competitors",
            "competitors",
            ["source_competitor_id"],
            ["id"],
        )

    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("evidence_key", sa.String(length=512), nullable=False),
        sa.Column("public_signal_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("topic", sa.String(length=128), nullable=True),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("strength", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("strength >= 0 AND strength <= 100", name="ck_evidence_strength"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 100", name="ck_evidence_confidence"
        ),
        sa.ForeignKeyConstraint(["public_signal_id"], ["public_signals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidence_key", name="uq_evidence_evidence_key"),
    )
    for column in ("evidence_key", "public_signal_id", "source_type", "topic", "intent", "observed_at"):
        op.create_index(f"ix_evidence_{column}", "evidence", [column])

    op.create_table(
        "business_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("alias_type", alias_type, nullable=False),
        sa.Column("value", sa.String(length=512), nullable=False),
        sa.Column("normalized_value", sa.String(length=512), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("evidence_id", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_business_aliases_confidence",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["business_entities.id"]),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id",
            "alias_type",
            "normalized_value",
            name="uq_business_aliases_business_type_value",
        ),
    )
    for column in ("business_id", "alias_type", "normalized_value", "evidence_id", "verified"):
        op.create_index(f"ix_business_aliases_{column}", "business_aliases", [column])

    _backfill_legacy_data()

    with op.batch_alter_table("public_signals") as batch:
        batch.alter_column(
            "contact_id", existing_type=sa.Integer(), nullable=True
        )
        batch.alter_column("dedupe_key", existing_type=sa.String(length=512), nullable=False)
        batch.create_unique_constraint(
            "uq_public_signals_external_identity",
            ["platform", "signal_type", "external_id"],
        )
        batch.create_check_constraint(
            "ck_public_signals_source_quality_score",
            "source_quality_score >= 0 AND source_quality_score <= 100",
        )
        batch.create_check_constraint(
            "ck_public_signals_confidence", "confidence >= 0 AND confidence <= 100"
        )
        for column in (
            "vertical",
            "subject_type",
            "business_id",
            "platform",
            "signal_type",
            "source_account",
            "source_competitor_id",
            "published_at",
            "discovered_at",
            "is_baseline",
        ):
            batch.create_index(f"ix_public_signals_{column}", [column])
        batch.create_index("ix_public_signals_dedupe_key", ["dedupe_key"], unique=True)


def _backfill_legacy_data() -> None:
    bind = op.get_bind()
    now = datetime.now(UTC)
    competitors = sa.table(
        "competitors",
        sa.column("id", sa.Integer),
        sa.column("business_id", sa.Integer),
        sa.column("display_name", sa.String),
        sa.column("normalized_handle", sa.String),
        sa.column("website_url", sa.Text),
        sa.column("category", sa.String),
    )
    businesses = sa.table(
        "business_entities",
        sa.column("id", sa.Integer),
        sa.column("canonical_key", sa.String),
        sa.column("canonical_name", sa.String),
        sa.column("normalized_name", sa.String),
        sa.column("verticals_json", sa.JSON),
        sa.column("website_url", sa.Text),
        sa.column("instagram_handle", sa.String),
        sa.column("primary_role", sa.String),
        sa.column("entity_status", sa.String),
        sa.column("confidence", sa.Integer),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    aliases = sa.table(
        "business_aliases",
        sa.column("business_id", sa.Integer),
        sa.column("alias_type", sa.String),
        sa.column("value", sa.String),
        sa.column("normalized_value", sa.String),
        sa.column("source_url", sa.Text),
        sa.column("confidence", sa.Integer),
        sa.column("verified", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    business_by_competitor: dict[int, int] = {}
    handle_by_competitor: dict[int, str] = {}
    for row in bind.execute(sa.select(competitors)).mappings():
        handle = str(row["normalized_handle"]).strip().lower()
        handle_by_competitor[int(row["id"])] = handle
        bind.execute(
            businesses.insert().values(
                canonical_key=f"legacy-competitor:{row['id']}",
                canonical_name=row["display_name"] or handle,
                normalized_name=str(row["display_name"] or handle).strip().lower(),
                verticals_json=["FURNITURE"],
                website_url=row["website_url"],
                instagram_handle=handle,
                primary_role=row["category"],
                entity_status="NEEDS_VERIFICATION",
                confidence=70,
                created_at=now,
                updated_at=now,
            )
        )
        business_id = int(
            bind.execute(
                sa.select(businesses.c.id).where(
                    businesses.c.canonical_key == f"legacy-competitor:{row['id']}"
                )
            ).scalar_one()
        )
        business_by_competitor[int(row["id"])] = business_id
        bind.execute(
            competitors.update()
            .where(competitors.c.id == row["id"])
            .values(business_id=business_id)
        )
        bind.execute(
            aliases.insert().values(
                business_id=business_id,
                alias_type="INSTAGRAM_HANDLE",
                value=handle,
                normalized_value=handle,
                source_url=f"https://www.instagram.com/{handle}/",
                confidence=100,
                verified=True,
                created_at=now,
            )
        )

    public_signals = sa.table(
        "public_signals",
        sa.column("id", sa.Integer),
        sa.column("comment_id", sa.Integer),
        sa.column("competitor_id", sa.Integer),
        sa.column("business_id", sa.Integer),
        sa.column("platform", sa.String),
        sa.column("signal_type", sa.String),
        sa.column("external_id", sa.String),
        sa.column("dedupe_key", sa.String),
        sa.column("source_url", sa.Text),
        sa.column("source_account", sa.String),
        sa.column("source_competitor_id", sa.Integer),
        sa.column("text", sa.Text),
        sa.column("payload_summary", sa.Text),
        sa.column("published_at", sa.DateTime(timezone=True)),
        sa.column("discovered_at", sa.DateTime(timezone=True)),
        sa.column("source_quality_score", sa.Integer),
        sa.column("confidence", sa.Integer),
        sa.column("is_baseline", sa.Boolean),
        sa.column("raw_data", sa.JSON),
    )
    comments = sa.table(
        "comments",
        sa.column("id", sa.Integer),
        sa.column("platform", sa.String),
        sa.column("platform_comment_id", sa.String),
        sa.column("post_id", sa.Integer),
        sa.column("text", sa.Text),
        sa.column("created_at_platform", sa.DateTime(timezone=True)),
        sa.column("discovered_at", sa.DateTime(timezone=True)),
        sa.column("is_baseline", sa.Boolean),
        sa.column("raw_data", sa.JSON),
    )
    posts = sa.table("posts", sa.column("id", sa.Integer), sa.column("url", sa.Text))
    evidence = sa.table(
        "evidence",
        sa.column("evidence_key", sa.String),
        sa.column("public_signal_id", sa.Integer),
        sa.column("source_type", sa.String),
        sa.column("source_url", sa.Text),
        sa.column("text", sa.Text),
        sa.column("strength", sa.Integer),
        sa.column("confidence", sa.Integer),
        sa.column("observed_at", sa.DateTime(timezone=True)),
        sa.column("raw_data", sa.JSON),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    rows = bind.execute(
        sa.select(public_signals.c.id, public_signals.c.competitor_id, comments, posts.c.url)
        .join(comments, comments.c.id == public_signals.c.comment_id)
        .join(posts, posts.c.id == comments.c.post_id)
    ).mappings()
    for row in rows:
        platform = str(row["platform"] or "instagram").lower()
        external_id = str(row["platform_comment_id"])
        dedupe_key = f"{platform}:COMMENT:{external_id}"
        competitor_id = int(row["competitor_id"])
        bind.execute(
            public_signals.update()
            .where(public_signals.c.id == row["id"])
            .values(
                business_id=business_by_competitor.get(competitor_id),
                platform=platform,
                signal_type="COMMENT",
                external_id=external_id,
                dedupe_key=dedupe_key,
                source_url=row["url"],
                source_account=handle_by_competitor.get(competitor_id),
                source_competitor_id=competitor_id,
                text=row["text"],
                payload_summary=str(row["text"] or "")[:500],
                published_at=row["created_at_platform"],
                discovered_at=row["discovered_at"] or now,
                source_quality_score=70,
                confidence=100,
                is_baseline=bool(row["is_baseline"]),
                raw_data=row["raw_data"],
            )
        )
        bind.execute(
            evidence.insert().values(
                evidence_key=f"{dedupe_key}:source",
                public_signal_id=row["id"],
                source_type="INSTAGRAM_COMMENT",
                source_url=row["url"],
                text=row["text"],
                strength=0,
                confidence=100,
                observed_at=row["created_at_platform"] or row["discovered_at"] or now,
                raw_data=row["raw_data"],
                created_at=now,
            )
        )


def downgrade() -> None:
    op.drop_table("business_aliases")
    op.drop_table("evidence")
    with op.batch_alter_table("public_signals") as batch:
        for column in (
            "is_baseline",
            "discovered_at",
            "published_at",
            "source_competitor_id",
            "source_account",
            "dedupe_key",
            "signal_type",
            "platform",
            "business_id",
            "subject_type",
            "vertical",
        ):
            batch.drop_index(f"ix_public_signals_{column}")
        batch.drop_constraint("ck_public_signals_confidence", type_="check")
        batch.drop_constraint("ck_public_signals_source_quality_score", type_="check")
        batch.drop_constraint("uq_public_signals_external_identity", type_="unique")
        batch.drop_constraint(
            "fk_public_signals_source_competitor_id_competitors", type_="foreignkey"
        )
        batch.drop_constraint(
            "fk_public_signals_business_id_business_entities", type_="foreignkey"
        )
        for column in (
            "raw_data",
            "is_baseline",
            "confidence",
            "source_quality_score",
            "discovered_at",
            "published_at",
            "payload_summary",
            "text",
            "source_competitor_id",
            "source_account",
            "source_url",
            "dedupe_key",
            "external_id",
            "signal_type",
            "platform",
            "business_id",
            "subject_type",
            "vertical",
        ):
            batch.drop_column(column)
        batch.alter_column(
            "contact_id", existing_type=sa.Integer(), nullable=False
        )
    with op.batch_alter_table("contact_events") as batch:
        batch.alter_column(
            "event_type",
            existing_type=contact_event_type,
            type_=sa.String(length=23),
            existing_nullable=False,
        )
    with op.batch_alter_table("competitors") as batch:
        batch.drop_index("ix_competitors_business_id")
        batch.drop_constraint(
            "fk_competitors_business_id_business_entities", type_="foreignkey"
        )
        batch.drop_column("business_id")
    with op.batch_alter_table("market_candidates") as batch:
        batch.drop_index("ix_market_candidates_vertical")
        batch.drop_column("contact_hint")
        batch.drop_column("vertical")
    for index in (
        "ix_business_entities_entity_status",
        "ix_business_entities_primary_role",
        "ix_business_entities_instagram_handle",
        "ix_business_entities_normalized_name",
        "ix_business_entities_canonical_key",
    ):
        op.drop_index(index, table_name="business_entities")
    op.drop_table("business_entities")
