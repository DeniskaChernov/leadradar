"""propagate artificial rattan vertical to commercial entities

Revision ID: a6d4e2c91f30
Revises: f3b9d7a61c20
Create Date: 2026-08-28 00:15:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a6d4e2c91f30"
down_revision: str | Sequence[str] | None = "f3b9d7a61c20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    vertical = sa.Enum(
        "FURNITURE", "ARTIFICIAL_RATTAN", name="vertical", native_enum=False
    )
    for table in ("competitors", "evidence", "audience_segments", "leads"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "vertical",
                    vertical,
                    nullable=False,
                    server_default="FURNITURE",
                )
            )
            batch.create_index(f"ix_{table}_vertical", ["vertical"])

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE evidence
            SET vertical = COALESCE(
                (SELECT public_signals.vertical
                 FROM public_signals
                 WHERE public_signals.id = evidence.public_signal_id),
                'FURNITURE'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE leads
            SET vertical = COALESCE(
                (SELECT public_signals.vertical
                 FROM public_signals
                 WHERE public_signals.comment_id = leads.comment_id),
                'FURNITURE'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE audience_segments
            SET vertical = 'ARTIFICIAL_RATTAN'
            WHERE slug IN ('rattan', 'rattan-wholesale', 'rattan-high-value')
            """
        )
    )


def downgrade() -> None:
    for table in ("leads", "audience_segments", "evidence", "competitors"):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_vertical")
            batch.drop_column("vertical")
