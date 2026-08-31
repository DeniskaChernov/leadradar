"""add evidence-first audience engine v3

Revision ID: f3b9d7a61c20
Revises: e8a4c2f91b70
Create Date: 2026-08-27 23:35:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3b9d7a61c20"
down_revision: str | Sequence[str] | None = "e8a4c2f91b70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interest_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("interest_key", sa.String(length=512), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("public_signal_id", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("competitor_id", sa.Integer(), nullable=False),
        sa.Column("vertical", sa.String(length=64), nullable=False, server_default="FURNITURE"),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("topic", sa.String(length=128), nullable=False),
        sa.Column("strength", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("half_life_days", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_interest_evidence_confidence",
        ),
        sa.CheckConstraint(
            "half_life_days > 0",
            name="ck_interest_evidence_half_life_days",
        ),
        sa.CheckConstraint(
            "strength >= 0 AND strength <= 100",
            name="ck_interest_evidence_strength",
        ),
        sa.ForeignKeyConstraint(["competitor_id"], ["competitors.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"]),
        sa.ForeignKeyConstraint(["public_signal_id"], ["public_signals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("interest_key", name="uq_interest_evidence_interest_key"),
    )
    for column in (
        "interest_key",
        "contact_id",
        "public_signal_id",
        "evidence_id",
        "competitor_id",
        "vertical",
        "dimension",
        "topic",
        "observed_at",
        "expires_at",
        "active",
    ):
        op.create_index(f"ix_interest_evidence_{column}", "interest_evidence", [column])

    op.create_table(
        "contact_interest_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("vertical", sa.String(length=64), nullable=False, server_default="FURNITURE"),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("topic", sa.String(length=128), nullable=False),
        sa.Column("current_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("commercial_signal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("competitor_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="confidence",
        ),
        sa.CheckConstraint(
            "current_score >= 0 AND current_score <= 100",
            name="current_score",
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "contact_id",
            "vertical",
            "dimension",
            "topic",
            name="uq_contact_interest_profiles_scope",
        ),
    )
    for column in (
        "contact_id",
        "vertical",
        "dimension",
        "topic",
        "last_seen_at",
    ):
        op.create_index(
            f"ix_contact_interest_profiles_{column}",
            "contact_interest_profiles",
            [column],
        )

    op.create_table(
        "outcome_dna",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("vertical", sa.String(length=64), nullable=False, server_default="FURNITURE"),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("product_topics_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("intents_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("buyer_role", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
        sa.Column("quantity_band", sa.String(length=32)),
        sa.Column(
            "commercial_stage",
            sa.String(length=64),
            nullable=False,
            server_default="NON_COMMERCIAL",
        ),
        sa.Column("commercial_signal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("competitor_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("engine_version", sa.String(length=32), nullable=False, server_default="3.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deal_id", name="uq_outcome_dna_deal_id"),
    )
    for column in ("deal_id", "contact_id", "vertical", "cutoff_at", "buyer_role"):
        op.create_index(f"ix_outcome_dna_{column}", "outcome_dna", [column])

    with op.batch_alter_table("audience_memberships") as batch:
        batch.add_column(
            sa.Column("reasons_json", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("evidence_ids_json", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("engine_version", sa.String(length=32), nullable=False, server_default="3.0")
        )


def downgrade() -> None:
    with op.batch_alter_table("audience_memberships") as batch:
        batch.drop_column("engine_version")
        batch.drop_column("evidence_ids_json")
        batch.drop_column("reasons_json")
    op.drop_table("outcome_dna")
    op.drop_table("contact_interest_profiles")
    op.drop_table("interest_evidence")
