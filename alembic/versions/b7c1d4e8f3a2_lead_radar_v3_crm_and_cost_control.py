"""lead radar v3 crm and cost control

Revision ID: b7c1d4e8f3a2
Revises: 9c41aef2d902
Create Date: 2026-08-26 16:15:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c1d4e8f3a2"
down_revision: str | Sequence[str] | None = "9c41aef2d902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("competitors") as batch:
        batch.add_column(sa.Column("category", sa.String(length=64), nullable=False, server_default="DIRECT"))
        batch.add_column(sa.Column("tier", sa.String(length=8), nullable=False, server_default="A"))
        batch.add_column(sa.Column("poll_interval_seconds", sa.Integer(), nullable=False, server_default="180"))
        batch.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("scan_error_count", sa.Integer(), nullable=False, server_default="0"))
        batch.create_index("ix_competitors_tier", ["tier"], unique=False)

    with op.batch_alter_table("leads") as batch:
        batch.add_column(sa.Column("ai_source", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("ai_attempt_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("ai_last_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("next_action_note", sa.Text(), nullable=True))
        batch.create_index("ix_leads_next_action_at", ["next_action_at"], unique=False)

    op.create_table(
        "contact_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("manager_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contact_tasks_contact_id", "contact_tasks", ["contact_id"], unique=False)
    op.create_index("ix_contact_tasks_lead_id", "contact_tasks", ["lead_id"], unique=False)
    op.create_index("ix_contact_tasks_manager_telegram_id", "contact_tasks", ["manager_telegram_id"], unique=False)
    op.create_index("ix_contact_tasks_due_at", "contact_tasks", ["due_at"], unique=False)
    op.create_index("ix_contact_tasks_status", "contact_tasks", ["status"], unique=False)

    op.create_table(
        "analysis_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_cache_cache_key", "analysis_cache", ["cache_key"], unique=True)

    op.create_table(
        "external_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_external_usage_service", "external_usage", ["service"], unique=False)
    op.create_index("ix_external_usage_operation", "external_usage", ["operation"], unique=False)
    op.create_index("ix_external_usage_created_at", "external_usage", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_external_usage_created_at", table_name="external_usage")
    op.drop_index("ix_external_usage_operation", table_name="external_usage")
    op.drop_index("ix_external_usage_service", table_name="external_usage")
    op.drop_table("external_usage")

    op.drop_index("ix_analysis_cache_cache_key", table_name="analysis_cache")
    op.drop_table("analysis_cache")

    op.drop_index("ix_contact_tasks_status", table_name="contact_tasks")
    op.drop_index("ix_contact_tasks_due_at", table_name="contact_tasks")
    op.drop_index("ix_contact_tasks_manager_telegram_id", table_name="contact_tasks")
    op.drop_index("ix_contact_tasks_lead_id", table_name="contact_tasks")
    op.drop_index("ix_contact_tasks_contact_id", table_name="contact_tasks")
    op.drop_table("contact_tasks")

    with op.batch_alter_table("leads") as batch:
        batch.drop_index("ix_leads_next_action_at")
        batch.drop_column("next_action_note")
        batch.drop_column("next_action_at")
        batch.drop_column("ai_last_attempt_at")
        batch.drop_column("ai_attempt_count")
        batch.drop_column("ai_source")

    with op.batch_alter_table("competitors") as batch:
        batch.drop_index("ix_competitors_tier")
        batch.drop_column("scan_error_count")
        batch.drop_column("last_scanned_at")
        batch.drop_column("notes")
        batch.drop_column("poll_interval_seconds")
        batch.drop_column("tier")
        batch.drop_column("category")
