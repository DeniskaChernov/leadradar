"""market competitor registry

Revision ID: e2c7a4f91b20
Revises: d4e8f1a2b3c4
Create Date: 2026-08-26 19:20:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2c7a4f91b20"
down_revision: str | Sequence[str] | None = "d4e8f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("competitors") as batch:
        batch.add_column(sa.Column("website_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("catalog_managed", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "market_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("instagram_handle", sa.String(length=255), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False, server_default="DIRECT"),
        sa.Column("tier", sa.String(length=8), nullable=False, server_default="B"),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DISCOVERED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("display_name", name="uq_market_candidates_display_name"),
    )
    op.create_index("ix_market_candidates_instagram_handle", "market_candidates", ["instagram_handle"])
    op.create_index("ix_market_candidates_category", "market_candidates", ["category"])
    op.create_index("ix_market_candidates_tier", "market_candidates", ["tier"])
    op.create_index("ix_market_candidates_status", "market_candidates", ["status"])


def downgrade() -> None:
    op.drop_index("ix_market_candidates_status", table_name="market_candidates")
    op.drop_index("ix_market_candidates_tier", table_name="market_candidates")
    op.drop_index("ix_market_candidates_category", table_name="market_candidates")
    op.drop_index("ix_market_candidates_instagram_handle", table_name="market_candidates")
    op.drop_table("market_candidates")
    with op.batch_alter_table("competitors") as batch:
        batch.drop_column("catalog_managed")
        batch.drop_column("website_url")
