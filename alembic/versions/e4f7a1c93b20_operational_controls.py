"""Operational UI toggles for Live Radar and OpenAI.

Revision ID: e4f7a1c93b20
Revises: d9e4b1c82a70
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4f7a1c93b20"
down_revision: str | Sequence[str] | None = "d9e4b1c82a70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operational_controls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("radar_live_armed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("openai_live_armed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_scan_credits", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_operational_controls_singleton"),
        sa.CheckConstraint(
            "default_scan_credits > 0 AND default_scan_credits <= 50",
            name="ck_operational_controls_default_scan_credits_range",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operational_controls_radar_live_armed",
        "operational_controls",
        ["radar_live_armed"],
    )
    op.create_index(
        "ix_operational_controls_openai_live_armed",
        "operational_controls",
        ["openai_live_armed"],
    )
    op.execute(
        sa.text(
            "INSERT INTO operational_controls "
            "(id, radar_live_armed, openai_live_armed, default_scan_credits, updated_at, created_at) "
            "VALUES (1, FALSE, FALSE, 5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_operational_controls_openai_live_armed", table_name="operational_controls")
    op.drop_index("ix_operational_controls_radar_live_armed", table_name="operational_controls")
    op.drop_table("operational_controls")
