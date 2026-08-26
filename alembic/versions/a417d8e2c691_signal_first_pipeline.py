"""add signal-first notification pipeline

Revision ID: a417d8e2c691
Revises: f31a8c74d920
Create Date: 2026-08-27 12:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a417d8e2c691"
down_revision: str | Sequence[str] | None = "f31a8c74d920"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    notification_policy = sa.Enum(
        "ALL_NEW_COMMENTS",
        "COMMERCIAL_ONLY",
        "HOT_ONLY",
        name="notificationpolicy",
        native_enum=False,
    )
    signal_status = sa.Enum(
        "ANALYZING", "ANALYZED", "FAILED", name="publicsignalstatus", native_enum=False
    )
    with op.batch_alter_table("competitors") as batch:
        batch.add_column(sa.Column("notification_policy", notification_policy, nullable=True))
        batch.create_index(
            "ix_competitors_notification_policy", ["notification_policy"], unique=False
        )
    with op.batch_alter_table("notification_logs") as batch:
        batch.add_column(
            sa.Column("content_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column("enrichment_followup_sent_at", sa.DateTime(timezone=True), nullable=True)
        )
    op.create_table(
        "public_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("comment_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("competitor_id", sa.Integer(), nullable=False),
        sa.Column("status", signal_status, nullable=False, server_default="ANALYZING"),
        sa.Column("pipeline_stage", sa.String(length=64), nullable=False, server_default="PERSISTED"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["comment_id"], ["comments.id"]),
        sa.ForeignKeyConstraint(["competitor_id"], ["competitors.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("comment_id", name="uq_public_signals_comment_id"),
    )
    op.create_index("ix_public_signals_comment_id", "public_signals", ["comment_id"])
    op.create_index("ix_public_signals_competitor_id", "public_signals", ["competitor_id"])
    op.create_index("ix_public_signals_contact_id", "public_signals", ["contact_id"])
    op.create_index("ix_public_signals_status", "public_signals", ["status"])

    # Existing comments are immutable history. Backfill their signal rows without creating
    # notifications or contact events.
    op.execute(
        sa.text(
            """
            INSERT INTO public_signals
                (comment_id, contact_id, competitor_id, status, pipeline_stage, created_at, updated_at)
            SELECT c.id, c.contact_id, c.competitor_id,
                   'ANALYZED', 'LEGACY_COMPLETE', c.discovered_at, c.discovered_at
            FROM comments AS c
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_public_signals_status", table_name="public_signals")
    op.drop_index("ix_public_signals_contact_id", table_name="public_signals")
    op.drop_index("ix_public_signals_competitor_id", table_name="public_signals")
    op.drop_index("ix_public_signals_comment_id", table_name="public_signals")
    op.drop_table("public_signals")
    with op.batch_alter_table("notification_logs") as batch:
        batch.drop_column("enrichment_followup_sent_at")
        batch.drop_column("content_version")
    with op.batch_alter_table("competitors") as batch:
        batch.drop_index("ix_competitors_notification_policy")
        batch.drop_column("notification_policy")
