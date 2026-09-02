"""Daily quality report idempotency logs.

Revision ID: c1d2e3f4a5b6
Revises: b9c0d1e2f3a4
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "b9c0d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_quality_report_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("report_timezone", sa.String(length=64), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "report_date",
            "report_timezone",
            name="uq_daily_quality_report_day_tz",
        ),
    )
    op.create_index(
        "ix_daily_quality_report_logs_report_date",
        "daily_quality_report_logs",
        ["report_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_daily_quality_report_logs_report_date", table_name="daily_quality_report_logs")
    op.drop_table("daily_quality_report_logs")
