"""add audience profile dna fields to contact_intelligence

Revision ID: a1b2c3d4e5f6
Revises: 7d2c4e8f1a90
Create Date: 2026-08-27 22:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "7d2c4e8f1a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("contact_intelligence") as batch:
        batch.add_column(
            sa.Column(
                "primary_buyer_role",
                sa.String(length=32),
                nullable=False,
                server_default="UNKNOWN",
            )
        )
        batch.add_column(
            sa.Column("buyer_roles_json", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("similarity_vector_json", sa.JSON(), nullable=False, server_default="{}")
        )


def downgrade() -> None:
    with op.batch_alter_table("contact_intelligence") as batch:
        batch.drop_column("similarity_vector_json")
        batch.drop_column("evidence_count")
        batch.drop_column("buyer_roles_json")
        batch.drop_column("primary_buyer_role")
