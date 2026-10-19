"""Durable first-discovery provenance for search results without rebuilding history."""

import sqlalchemy as sa

from alembic import op

revision = "ca219b748d30"
down_revision = "b9f2a6c81d40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("monitor_runs", sa.Column("result_tracking_version", sa.Integer(), nullable=True))
    op.add_column("monitor_runs", sa.Column("vertical", sa.String(32), nullable=True))
    op.create_table(
        "search_result_origins",
        sa.Column("comment_id", sa.Integer(), sa.ForeignKey("comments.id"), primary_key=True),
        sa.Column("discovered_run_id", sa.Integer(), sa.ForeignKey("monitor_runs.id")),
        sa.Column("lead_run_id", sa.Integer(), sa.ForeignKey("monitor_runs.id")),
    )
    op.create_index("ix_search_result_origins_discovered_run_id", "search_result_origins", ["discovered_run_id"])
    op.create_index("ix_search_result_origins_lead_run_id", "search_result_origins", ["lead_run_id"])


def downgrade() -> None:
    op.drop_table("search_result_origins")
    with op.batch_alter_table("monitor_runs") as batch:
        batch.drop_column("vertical")
        batch.drop_column("result_tracking_version")
