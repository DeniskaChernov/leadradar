"""add manager-confirmed versioned FX policy

Revision ID: a3c8f7d24e10
Revises: f2a5b8d13c70
Create Date: 2026-08-30 21:35:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3c8f7d24e10"
down_revision: str | Sequence[str] | None = "f2a5b8d13c70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fx_rate_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("base_currency", sa.String(length=8), nullable=False),
        sa.Column("quote_currency", sa.String(length=8), nullable=False),
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("manager_telegram_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "base_currency",
            "quote_currency",
            "effective_from",
            name="uq_fx_rate_policies_pair_effective",
        ),
    )
    op.create_index(
        "ix_fx_rate_policies_base_currency",
        "fx_rate_policies",
        ["base_currency"],
    )
    op.create_index(
        "ix_fx_rate_policies_quote_currency",
        "fx_rate_policies",
        ["quote_currency"],
    )
    op.create_index(
        "ix_fx_rate_policies_effective_from",
        "fx_rate_policies",
        ["effective_from"],
    )
    op.create_index("ix_fx_rate_policies_active", "fx_rate_policies", ["active"])
    op.create_index(
        "ix_fx_rate_policies_manager_telegram_id",
        "fx_rate_policies",
        ["manager_telegram_id"],
    )
    op.create_index(
        "ix_fx_rate_policies_created_at",
        "fx_rate_policies",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("fx_rate_policies")
