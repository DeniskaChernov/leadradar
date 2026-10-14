"""Separate resumable reply threads and durable manual request identity."""

import sqlalchemy as sa

from alembic import op

revision = "b9f2a6c81d40"
down_revision = "b8d9e0f1a2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reply_thread_states",
        sa.Column("comment_id", sa.Integer(), sa.ForeignKey("comments.id"), primary_key=True),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("next_cursor", sa.Text()),
        sa.Column("coverage_status", sa.String(32), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("pages_fetched", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(128)),
        sa.Column("visited_cursors", sa.JSON(), nullable=False),
    )
    op.create_table(
        "reply_scan_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_key", sa.String(128), nullable=False, unique=True),
        sa.Column("comment_id", sa.Integer(), sa.ForeignKey("comments.id"), nullable=False),
        sa.Column("manager_id", sa.BigInteger(), nullable=False),
        sa.Column("max_credits", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_reply_scan_requests_comment_id", "reply_scan_requests", ["comment_id"])


def downgrade() -> None:
    op.drop_table("reply_scan_requests")
    op.drop_table("reply_thread_states")
