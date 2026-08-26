"""persist deep lead analysis

Revision ID: f31a8c74d920
Revises: e2c7a4f91b20
Create Date: 2026-08-26 18:40:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f31a8c74d920"
down_revision: str | Sequence[str] | None = "e2c7a4f91b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("leads") as batch:
        batch.add_column(sa.Column("analysis_details", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("leads") as batch:
        batch.drop_column("analysis_details")
