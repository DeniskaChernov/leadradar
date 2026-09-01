"""audience definition registry v4

Revision ID: c5a9f2e81d40
Revises: b4d1f8a62c30
Create Date: 2026-08-29 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5a9f2e81d40"
down_revision: str | Sequence[str] | None = "b4d1f8a62c30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("audience_segments") as batch_op:
        batch_op.add_column(
            sa.Column("audience_family", sa.String(32), nullable=False, server_default="INTENT")
        )
        batch_op.add_column(
            sa.Column("audience_level", sa.String(32), nullable=False, server_default="CORE")
        )
        batch_op.add_column(
            sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE")
        )
        batch_op.add_column(
            sa.Column("membership_strategy", sa.String(32), nullable=False, server_default="RULE")
        )
        batch_op.add_column(
            sa.Column("minimum_evidence_count", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(
            sa.Column("minimum_confidence", sa.Integer(), nullable=False, server_default="50")
        )
        batch_op.add_column(
            sa.Column("minimum_current_score", sa.Integer(), nullable=False, server_default="20")
        )
        batch_op.add_column(
            sa.Column("recency_policy_json", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.add_column(
            sa.Column("decay_policy_json", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.add_column(
            sa.Column(
                "meta_use_case", sa.String(32), nullable=False, server_default="ANALYSIS_ONLY"
            )
        )
        batch_op.add_column(
            sa.Column("created_by", sa.String(64), nullable=False, server_default="SYSTEM_REGISTRY")
        )
        batch_op.add_column(
            sa.Column("engine_version", sa.String(32), nullable=False, server_default="4.0")
        )
        batch_op.create_index("ix_audience_segments_audience_family", ["audience_family"])
        batch_op.create_index("ix_audience_segments_audience_level", ["audience_level"])
        batch_op.create_index("ix_audience_segments_status", ["status"])
        batch_op.create_index("ix_audience_segments_meta_use_case", ["meta_use_case"])


def downgrade() -> None:
    with op.batch_alter_table("audience_segments") as batch_op:
        batch_op.drop_index("ix_audience_segments_meta_use_case")
        batch_op.drop_index("ix_audience_segments_status")
        batch_op.drop_index("ix_audience_segments_audience_level")
        batch_op.drop_index("ix_audience_segments_audience_family")
        batch_op.drop_column("engine_version")
        batch_op.drop_column("created_by")
        batch_op.drop_column("meta_use_case")
        batch_op.drop_column("decay_policy_json")
        batch_op.drop_column("recency_policy_json")
        batch_op.drop_column("minimum_current_score")
        batch_op.drop_column("minimum_confidence")
        batch_op.drop_column("minimum_evidence_count")
        batch_op.drop_column("membership_strategy")
        batch_op.drop_column("status")
        batch_op.drop_column("audience_level")
        batch_op.drop_column("audience_family")
