"""discovery candidate snapshots and diffs

Revision ID: a7c9e2f51d40
Revises: d8e2b7c41a90
Create Date: 2026-08-28 14:30:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c9e2f51d40"
down_revision: str | Sequence[str] | None = "d8e2b7c41a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("market_candidates") as batch:
        batch.add_column(sa.Column("canonical_key", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("source", sa.String(length=64), nullable=False, server_default="MANUAL"))
        batch.add_column(sa.Column("source_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("location", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("snapshot", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_market_candidates_canonical_key", ["canonical_key"], unique=True)
        batch.create_index("ix_market_candidates_source", ["source"])
        batch.create_index("ix_market_candidates_snapshot_fingerprint", ["snapshot_fingerprint"])
        batch.create_index("ix_market_candidates_last_seen_at", ["last_seen_at"])

    op.create_table(
        "market_candidate_diffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("market_candidates.id"), nullable=False),
        sa.Column("diff_type", sa.String(length=32), nullable=False, server_default="UPDATED"),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("before_snapshot", sa.JSON(), nullable=True),
        sa.Column("after_snapshot", sa.JSON(), nullable=False),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("candidate_id", "snapshot_fingerprint", name="uq_candidate_diff_snapshot"),
    )
    op.create_index("ix_market_candidate_diffs_candidate_id", "market_candidate_diffs", ["candidate_id"])
    op.create_index("ix_market_candidate_diffs_diff_type", "market_candidate_diffs", ["diff_type"])
    op.create_index("ix_market_candidate_diffs_acknowledged_at", "market_candidate_diffs", ["acknowledged_at"])
    op.create_index("ix_market_candidate_diffs_created_at", "market_candidate_diffs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_market_candidate_diffs_created_at", table_name="market_candidate_diffs")
    op.drop_index("ix_market_candidate_diffs_acknowledged_at", table_name="market_candidate_diffs")
    op.drop_index("ix_market_candidate_diffs_diff_type", table_name="market_candidate_diffs")
    op.drop_index("ix_market_candidate_diffs_candidate_id", table_name="market_candidate_diffs")
    op.drop_table("market_candidate_diffs")
    with op.batch_alter_table("market_candidates") as batch:
        batch.drop_index("ix_market_candidates_last_seen_at")
        batch.drop_index("ix_market_candidates_snapshot_fingerprint")
        batch.drop_index("ix_market_candidates_source")
        batch.drop_index("ix_market_candidates_canonical_key")
        batch.drop_column("last_seen_at")
        batch.drop_column("snapshot_fingerprint")
        batch.drop_column("snapshot")
        batch.drop_column("location")
        batch.drop_column("source_url")
        batch.drop_column("source")
        batch.drop_column("canonical_key")
