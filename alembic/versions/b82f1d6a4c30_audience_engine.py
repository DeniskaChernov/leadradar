"""add audience engine

Revision ID: b82f1d6a4c30
Revises: a417d8e2c691
Create Date: 2026-08-27 13:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b82f1d6a4c30"
down_revision: str | Sequence[str] | None = "a417d8e2c691"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    export_eligibility = sa.Enum(
        "NOT_EXPORTABLE",
        "FIRST_PARTY_ELIGIBLE",
        "EXPORTED",
        name="exporteligibility",
        native_enum=False,
    )
    op.create_table(
        "audience_segments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("criteria_json", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audience_segments_active", "audience_segments", ["active"])
    op.create_index("ix_audience_segments_slug", "audience_segments", ["slug"], unique=True)
    op.create_table(
        "contact_intelligence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("vertical", sa.String(length=64), nullable=False),
        sa.Column("commercial_stage", sa.String(length=64), nullable=False),
        sa.Column("intent_strength", sa.Integer(), nullable=False),
        sa.Column("signal_count", sa.Integer(), nullable=False),
        sa.Column("commercial_signal_count", sa.Integer(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("competitor_count", sa.Integer(), nullable=False),
        sa.Column("activity_score", sa.Integer(), nullable=False),
        sa.Column("value_score", sa.Integer(), nullable=False),
        sa.Column("fit_score", sa.Integer(), nullable=False),
        sa.Column("customer_type", sa.String(length=16), nullable=False),
        sa.Column("quantity_band", sa.String(length=32), nullable=True),
        sa.Column("purchase_horizon", sa.String(length=32), nullable=True),
        sa.Column("product_interests_json", sa.JSON(), nullable=False),
        sa.Column("top_intents_json", sa.JSON(), nullable=False),
        sa.Column("export_eligibility", export_eligibility, nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contact_id", name="uq_contact_intelligence_contact_id"),
    )
    op.create_index("ix_contact_intelligence_contact_id", "contact_intelligence", ["contact_id"])
    op.create_index(
        "ix_contact_intelligence_export_eligibility",
        "contact_intelligence",
        ["export_eligibility"],
    )
    op.create_index(
        "ix_contact_intelligence_last_seen_at", "contact_intelligence", ["last_seen_at"]
    )
    op.create_table(
        "audience_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["segment_id"], ["audience_segments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "segment_id", "contact_id", name="uq_audience_memberships_segment_contact"
        ),
    )
    op.create_index("ix_audience_memberships_active", "audience_memberships", ["active"])
    op.create_index("ix_audience_memberships_contact_id", "audience_memberships", ["contact_id"])
    op.create_index("ix_audience_memberships_expires_at", "audience_memberships", ["expires_at"])
    op.create_index("ix_audience_memberships_segment_id", "audience_memberships", ["segment_id"])


def downgrade() -> None:
    op.drop_index("ix_audience_memberships_segment_id", table_name="audience_memberships")
    op.drop_index("ix_audience_memberships_expires_at", table_name="audience_memberships")
    op.drop_index("ix_audience_memberships_contact_id", table_name="audience_memberships")
    op.drop_index("ix_audience_memberships_active", table_name="audience_memberships")
    op.drop_table("audience_memberships")
    op.drop_index("ix_contact_intelligence_last_seen_at", table_name="contact_intelligence")
    op.drop_index("ix_contact_intelligence_export_eligibility", table_name="contact_intelligence")
    op.drop_index("ix_contact_intelligence_contact_id", table_name="contact_intelligence")
    op.drop_table("contact_intelligence")
    op.drop_index("ix_audience_segments_slug", table_name="audience_segments")
    op.drop_index("ix_audience_segments_active", table_name="audience_segments")
    op.drop_table("audience_segments")
