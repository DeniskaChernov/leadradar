"""Persist publication traversal independently for each source and provider."""

import sqlalchemy as sa

from alembic import op

revision = "b8d9e0f1a2c3"
down_revision = "a7c8d9e0f1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_discovery_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("competitor_id", sa.Integer(), sa.ForeignKey("competitors.id"), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("next_cursor", sa.Text(), nullable=True),
        sa.Column("coverage_status", sa.Enum("UNKNOWN", "FULL", "PARTIAL", "LATEST_ONLY", native_enum=False), nullable=False),
        sa.Column("head_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("page_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_reason", sa.String(64), nullable=True),
        sa.Column("visited_cursors", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("competitor_id", "provider", name="uq_post_discovery_source_provider"),
    )
    op.create_index("ix_post_discovery_states_competitor_id", "post_discovery_states", ["competitor_id"])


def downgrade() -> None:
    op.drop_index("ix_post_discovery_states_competitor_id", table_name="post_discovery_states")
    op.drop_table("post_discovery_states")
