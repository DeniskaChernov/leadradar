"""Добавить persisted state детерминированного adaptive monitoring.

Revision ID: c8f3a1d57b20
Revises: b7d9e2a46f10
"""

import sqlalchemy as sa

from alembic import op

revision = "c8f3a1d57b20"
down_revision = "b7d9e2a46f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("competitors") as batch:
        batch.add_column(
            sa.Column(
                "monitoring_state",
                sa.String(16),
                nullable=False,
                server_default="DORMANT",
            )
        )
        batch.add_column(sa.Column("next_scan_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column(
                "adaptive_priority_score",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "adaptive_reasons_json",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            )
        )
        batch.add_column(
            sa.Column("adaptive_policy_version", sa.String(64), nullable=True)
        )
        batch.create_index(
            "ix_competitors_monitoring_state",
            ["monitoring_state"],
            unique=False,
        )
        batch.create_index("ix_competitors_next_scan_at", ["next_scan_at"], unique=False)
    op.execute(
        sa.text(
            "UPDATE competitors SET next_scan_at = last_scanned_at "
            "WHERE last_scanned_at IS NOT NULL"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("competitors") as batch:
        batch.drop_index("ix_competitors_next_scan_at")
        batch.drop_index("ix_competitors_monitoring_state")
        batch.drop_column("adaptive_policy_version")
        batch.drop_column("adaptive_reasons_json")
        batch.drop_column("adaptive_priority_score")
        batch.drop_column("next_scan_at")
        batch.drop_column("monitoring_state")
