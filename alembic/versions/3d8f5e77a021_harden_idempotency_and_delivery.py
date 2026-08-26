"""harden idempotency and delivery

Revision ID: 3d8f5e77a021
Revises: 0c86535d8581
Create Date: 2026-08-26 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3d8f5e77a021"
down_revision: str | Sequence[str] | None = "0c86535d8581"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "posts", sa.Column("comments_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "notification_logs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "notification_logs",
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notification_logs",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    with op.batch_alter_table("posts") as batch_op:
        batch_op.create_unique_constraint("uq_posts_platform_url", ["platform", "url"])
    with op.batch_alter_table("deals") as batch_op:
        batch_op.create_unique_constraint("uq_deals_lead_id", ["lead_id"])


def downgrade() -> None:
    with op.batch_alter_table("deals") as batch_op:
        batch_op.drop_constraint("uq_deals_lead_id", type_="unique")
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("uq_posts_platform_url", type_="unique")
    op.drop_column("notification_logs", "next_attempt_at")
    op.drop_column("notification_logs", "last_attempt_at")
    op.drop_column("notification_logs", "attempt_count")
    op.drop_column("posts", "comments_checked_at")
