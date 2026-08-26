"""contact qualification and crm recovery actions

Revision ID: d4e8f1a2b3c4
Revises: b7c1d4e8f3a2
Create Date: 2026-08-26 17:20:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e8f1a2b3c4"
down_revision: str | Sequence[str] | None = "b7c1d4e8f3a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("contacts") as batch:
        batch.add_column(sa.Column("phone", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("preferred_channel", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("city", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("interest_summary", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("desired_quantity", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("budget_from", sa.Numeric(14, 2), nullable=True))
        batch.add_column(sa.Column("budget_to", sa.Numeric(14, 2), nullable=True))
        batch.add_column(sa.Column("desired_color", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("purchase_timeline", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("qualification_note", sa.Text(), nullable=True))
        batch.add_column(sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("qualification_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("contacts") as batch:
        batch.drop_column("qualification_updated_at")
        batch.drop_column("last_contacted_at")
        batch.drop_column("qualification_note")
        batch.drop_column("purchase_timeline")
        batch.drop_column("desired_color")
        batch.drop_column("budget_to")
        batch.drop_column("budget_from")
        batch.drop_column("desired_quantity")
        batch.drop_column("interest_summary")
        batch.drop_column("city")
        batch.drop_column("preferred_channel")
        batch.drop_column("phone")
