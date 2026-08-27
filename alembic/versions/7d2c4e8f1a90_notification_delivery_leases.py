"""add durable notification delivery leases

Revision ID: 7d2c4e8f1a90
Revises: 4b1f6a9c2d70
Create Date: 2026-08-27 19:20:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7d2c4e8f1a90"
down_revision: str | Sequence[str] | None = "4b1f6a9c2d70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("notification_logs") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("enrichment_followup_started_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("lease_owner", sa.String(length=128)))
        batch.add_column(sa.Column("lease_token", sa.String(length=64)))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("delivery_started_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("uncertain_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("resolution", sa.String(length=64)))
        batch.add_column(sa.Column("edit_claim_token", sa.String(length=64)))
        batch.add_column(sa.Column("edit_lease_expires_at", sa.DateTime(timezone=True)))
        batch.add_column(
            sa.Column("edit_attempt_count", sa.Integer(), nullable=False, server_default="0")
        )

    with op.batch_alter_table("significant_change_notifications") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("lease_owner", sa.String(length=128)))
        batch.add_column(sa.Column("lease_token", sa.String(length=64)))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("delivery_started_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("uncertain_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("resolution", sa.String(length=64)))

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE notification_logs "
            "SET idempotency_key = 'lead:' || lead_id || ':chat:' || chat_id"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE significant_change_notifications "
            "SET idempotency_key = 'change:' || change_id || ':chat:' || chat_id"
        )
    )

    with op.batch_alter_table("notification_logs") as batch:
        batch.alter_column(
            "idempotency_key", existing_type=sa.String(length=255), nullable=False
        )
        batch.create_index(
            "ix_notification_logs_idempotency_key", ["idempotency_key"], unique=True
        )
        for column in (
            "lease_owner",
            "lease_token",
            "lease_expires_at",
            "uncertain_at",
            "edit_claim_token",
        ):
            batch.create_index(f"ix_notification_logs_{column}", [column])

    with op.batch_alter_table("significant_change_notifications") as batch:
        batch.alter_column(
            "idempotency_key", existing_type=sa.String(length=255), nullable=False
        )
        batch.create_index(
            "ix_significant_change_notifications_idempotency_key",
            ["idempotency_key"],
            unique=True,
        )
        for column in ("lease_owner", "lease_token", "lease_expires_at", "uncertain_at"):
            batch.create_index(
                f"ix_significant_change_notifications_{column}", [column]
            )


def downgrade() -> None:
    with op.batch_alter_table("significant_change_notifications") as batch:
        for column in (
            "uncertain_at",
            "lease_expires_at",
            "lease_token",
            "lease_owner",
            "idempotency_key",
        ):
            batch.drop_index(f"ix_significant_change_notifications_{column}")
        for column in (
            "resolution",
            "resolved_at",
            "uncertain_at",
            "delivery_started_at",
            "lease_expires_at",
            "lease_token",
            "lease_owner",
            "idempotency_key",
        ):
            batch.drop_column(column)

    with op.batch_alter_table("notification_logs") as batch:
        for column in (
            "edit_claim_token",
            "uncertain_at",
            "lease_expires_at",
            "lease_token",
            "lease_owner",
            "idempotency_key",
        ):
            batch.drop_index(f"ix_notification_logs_{column}")
        for column in (
            "edit_attempt_count",
            "edit_lease_expires_at",
            "edit_claim_token",
            "resolution",
            "resolved_at",
            "uncertain_at",
            "delivery_started_at",
            "lease_expires_at",
            "lease_token",
            "lease_owner",
            "enrichment_followup_started_at",
            "idempotency_key",
        ):
            batch.drop_column(column)
