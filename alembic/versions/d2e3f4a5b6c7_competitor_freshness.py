"""Competitor publication freshness fields.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "competitors",
        sa.Column("latest_publication_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "competitors",
        sa.Column(
            "freshness_status",
            sa.String(length=16),
            nullable=False,
            server_default="UNKNOWN",
        ),
    )
    op.add_column(
        "competitors",
        sa.Column("freshness_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "competitors",
        sa.Column("freshness_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "competitors",
        sa.Column(
            "manual_freshness_confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_competitors_freshness_status",
        "competitors",
        ["freshness_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_competitors_freshness_status", table_name="competitors")
    op.drop_column("competitors", "manual_freshness_confirmed_at")
    op.drop_column("competitors", "freshness_checked_at")
    op.drop_column("competitors", "freshness_reason")
    op.drop_column("competitors", "freshness_status")
    op.drop_column("competitors", "latest_publication_at")
