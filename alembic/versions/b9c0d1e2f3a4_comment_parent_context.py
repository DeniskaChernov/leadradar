"""Comment parent context for reply «+» analysis.

Revision ID: b9c0d1e2f3a4
Revises: c4d5e6f7a8b9
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: str | Sequence[str] | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("comments") as batch:
        batch.add_column(
            sa.Column("parent_platform_comment_id", sa.String(length=255), nullable=True)
        )
        batch.add_column(sa.Column("parent_comment_text", sa.Text(), nullable=True))
        batch.create_index(
            "ix_comments_parent_platform_comment_id",
            ["parent_platform_comment_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("comments") as batch:
        batch.drop_index("ix_comments_parent_platform_comment_id")
        batch.drop_column("parent_comment_text")
        batch.drop_column("parent_platform_comment_id")
