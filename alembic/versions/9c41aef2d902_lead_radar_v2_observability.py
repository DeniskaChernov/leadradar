"""lead radar v2 observability and comment coverage

Revision ID: 9c41aef2d902
Revises: 6a7b92dce104
Create Date: 2026-08-26 15:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9c41aef2d902"
down_revision: str | Sequence[str] | None = "6a7b92dce104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    coverage = sa.Enum(
        "UNKNOWN", "FULL", "PARTIAL", "LATEST_ONLY", name="coveragestatus", native_enum=False
    )
    run_status = sa.Enum(
        "RUNNING", "SUCCESS", "FAILED", name="monitorrunstatus", native_enum=False
    )
    with op.batch_alter_table("posts") as batch_op:
        batch_op.add_column(sa.Column("last_synced_remote_count", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("comment_pages_fetched", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("coverage_status", coverage, nullable=False, server_default="UNKNOWN")
        )
        batch_op.add_column(sa.Column("last_comment_provider", sa.String(length=128), nullable=True))
        batch_op.create_index("ix_posts_coverage_status", ["coverage_status"], unique=False)

    # Preserve the old optimization marker as the remote count, then correct comments_fetched_count
    # so it means what its name says: comments actually present from the last/known fetch.
    op.execute("UPDATE posts SET last_synced_remote_count = comments_fetched_count")
    op.execute(
        "UPDATE posts SET comments_fetched_count = "
        "(SELECT COUNT(*) FROM comments WHERE comments.post_id = posts.id)"
    )
    op.execute(
        "UPDATE posts SET coverage_status = CASE "
        "WHEN comments_count <= comments_fetched_count THEN 'FULL' "
        "WHEN comments_fetched_count > 0 THEN 'PARTIAL' ELSE 'UNKNOWN' END"
    )

    op.create_table(
        "monitor_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=True),
        sa.Column("status", run_status, nullable=False),
        sa.Column("stats_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_monitor_runs")),
    )
    op.create_index("ix_monitor_runs_trigger", "monitor_runs", ["trigger"], unique=False)
    op.create_index("ix_monitor_runs_status", "monitor_runs", ["status"], unique=False)
    op.create_index("ix_monitor_runs_started_at", "monitor_runs", ["started_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_monitor_runs_started_at", table_name="monitor_runs")
    op.drop_index("ix_monitor_runs_status", table_name="monitor_runs")
    op.drop_index("ix_monitor_runs_trigger", table_name="monitor_runs")
    op.drop_table("monitor_runs")
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_index("ix_posts_coverage_status")
        batch_op.drop_column("last_comment_provider")
        batch_op.drop_column("coverage_status")
        batch_op.drop_column("comment_pages_fetched")
        batch_op.drop_column("last_synced_remote_count")
