"""add durable AI request and external budget ledgers

Revision ID: e8a4c2f91b70
Revises: b1c2d3e4f5a6
Create Date: 2026-08-27 21:05:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e8a4c2f91b70"
down_revision: str | Sequence[str] | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_budget_reservations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("units_reserved", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "estimated_cost_usd",
            sa.Numeric(precision=10, scale=6),
            nullable=False,
            server_default="0.000000",
        ),
        sa.Column("request_fingerprint", sa.String(length=64)),
        sa.Column(
            "status",
            sa.Enum(
                "RESERVED",
                "FINALIZED",
                "RELEASED",
                "EXPIRED",
                name="reservationstatus",
                native_enum=False,
            ),
            nullable=False,
            server_default="RESERVED",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "service",
        "operation",
        "request_fingerprint",
        "status",
        "expires_at",
        "created_at",
    ):
        op.create_index(
            f"ix_external_budget_reservations_{column}",
            "external_budget_reservations",
            [column],
        )

    op.create_table(
        "ai_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("context_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "CLAIMED",
                "SUCCEEDED",
                "FAILED",
                "RETRYABLE",
                "PERMANENT_FAILURE",
                name="airequeststatus",
                native_enum=False,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True)),
        sa.Column("worker_id", sa.String(length=128)),
        sa.Column("claim_token", sa.String(length=64)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "estimated_cost_usd",
            sa.Numeric(precision=10, scale=6),
            nullable=False,
            server_default="0.000000",
        ),
        sa.Column("actual_cost_usd", sa.Numeric(precision=10, scale=6)),
        sa.Column("response_cache_key", sa.String(length=64)),
        sa.Column("result_json", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "lead_id",
            "analysis_version",
            "context_fingerprint",
            name="uq_ai_requests_lead_version_fingerprint",
        ),
    )
    for column in (
        "lead_id",
        "analysis_version",
        "context_fingerprint",
        "status",
        "claim_expires_at",
        "worker_id",
        "response_cache_key",
        "created_at",
    ):
        op.create_index(f"ix_ai_requests_{column}", "ai_requests", [column])
    op.create_index("ix_ai_requests_claim_token", "ai_requests", ["claim_token"], unique=True)

    # The Phase 4 migration added the column but omitted its ORM-declared index.
    op.create_index(
        "ix_contact_intelligence_primary_buyer_role",
        "contact_intelligence",
        ["primary_buyer_role"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_contact_intelligence_primary_buyer_role",
        table_name="contact_intelligence",
    )
    op.drop_table("ai_requests")
    op.drop_table("external_budget_reservations")
