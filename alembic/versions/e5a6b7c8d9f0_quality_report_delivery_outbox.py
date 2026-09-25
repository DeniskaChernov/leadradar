"""Persist quality reports and recipient claims before Telegram delivery."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "e5a6b7c8d9f0"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("daily_quality_report_logs") as batch:
        batch.alter_column("sent_at", existing_type=sa.DateTime(timezone=True), nullable=True)
        batch.add_column(sa.Column("message_text", sa.Text(), nullable=True))
    op.create_table(
        "daily_quality_report_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("daily_quality_report_logs.id"), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("report_id", "chat_id", name="uq_quality_report_delivery_target"),
    )
    op.create_index("ix_daily_quality_report_deliveries_report_id", "daily_quality_report_deliveries", ["report_id"])
    op.create_index("ix_daily_quality_report_deliveries_status", "daily_quality_report_deliveries", ["status"])


def downgrade() -> None:
    # The old application sends before recording. Dropping pending delivery state could
    # duplicate messages; require resolution first, without silently inventing sent_at.
    pending = op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM daily_quality_report_logs WHERE sent_at IS NULL"))
    if pending:
        raise RuntimeError("Resolve outstanding quality reports before downgrading the outbox")
    op.drop_table("daily_quality_report_deliveries")
    with op.batch_alter_table("daily_quality_report_logs") as batch:
        batch.drop_column("message_text")
        batch.alter_column("sent_at", existing_type=sa.DateTime(timezone=True), nullable=False)
