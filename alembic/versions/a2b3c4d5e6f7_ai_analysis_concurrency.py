"""OpenAI analysis concurrency in operational_controls.

Revision ID: a2b3c4d5e6f7
Revises: f1a8c3e74b90
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | Sequence[str] | None = "f1a8c3e74b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("operational_controls") as batch:
        batch.add_column(
            sa.Column(
                "ai_analysis_max_concurrency",
                sa.Integer(),
                nullable=False,
                server_default="3",
            )
        )
        batch.create_check_constraint(
            "ck_operational_controls_ai_analysis_max_concurrency_range",
            "ai_analysis_max_concurrency >= 1 AND ai_analysis_max_concurrency <= 10",
        )


def downgrade() -> None:
    with op.batch_alter_table("operational_controls") as batch:
        batch.drop_constraint(
            "ck_operational_controls_ai_analysis_max_concurrency_range",
            type_="check",
        )
        batch.drop_column("ai_analysis_max_concurrency")
