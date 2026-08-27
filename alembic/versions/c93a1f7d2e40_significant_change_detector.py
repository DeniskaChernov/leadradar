"""add significant change detector

Revision ID: c93a1f7d2e40
Revises: b82f1d6a4c30
Create Date: 2026-08-27 14:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c93a1f7d2e40"
down_revision: str | Sequence[str] | None = "b82f1d6a4c30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "significant_changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("primary_type", sa.String(length=64), nullable=False),
        sa.Column("change_types_json", sa.JSON(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("previous_priority", sa.Integer(), nullable=False),
        sa.Column("current_priority", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=False),
        sa.Column("after_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lead_id", name="uq_significant_changes_lead_id"),
    )
    op.create_index("ix_significant_changes_contact_id", "significant_changes", ["contact_id"])
    op.create_index("ix_significant_changes_created_at", "significant_changes", ["created_at"])
    op.create_index("ix_significant_changes_lead_id", "significant_changes", ["lead_id"])
    op.create_index("ix_significant_changes_primary_type", "significant_changes", ["primary_type"])
    op.create_index("ix_significant_changes_severity", "significant_changes", ["severity"])

    notification_status = sa.Enum(
        "PENDING", "PROCESSING", "SENT", "FAILED", name="notificationstatus", native_enum=False
    )
    op.create_table(
        "significant_change_notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("change_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("status", notification_status, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["change_id"], ["significant_changes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "change_id", "chat_id", name="uq_significant_change_notifications_target"
        ),
    )
    op.create_index(
        "ix_significant_change_notifications_change_id",
        "significant_change_notifications",
        ["change_id"],
    )
    op.create_index(
        "ix_significant_change_notifications_chat_id",
        "significant_change_notifications",
        ["chat_id"],
    )
    op.create_index(
        "ix_significant_change_notifications_status",
        "significant_change_notifications",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_significant_change_notifications_status",
        table_name="significant_change_notifications",
    )
    op.drop_index(
        "ix_significant_change_notifications_chat_id",
        table_name="significant_change_notifications",
    )
    op.drop_index(
        "ix_significant_change_notifications_change_id",
        table_name="significant_change_notifications",
    )
    op.drop_table("significant_change_notifications")
    op.drop_index("ix_significant_changes_severity", table_name="significant_changes")
    op.drop_index("ix_significant_changes_primary_type", table_name="significant_changes")
    op.drop_index("ix_significant_changes_lead_id", table_name="significant_changes")
    op.drop_index("ix_significant_changes_created_at", table_name="significant_changes")
    op.drop_index("ix_significant_changes_contact_id", table_name="significant_changes")
    op.drop_table("significant_changes")
