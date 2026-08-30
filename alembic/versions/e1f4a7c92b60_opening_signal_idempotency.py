"""enforce opening signal idempotency

Revision ID: e1f4a7c92b60
Revises: d6b1e4f92a50
Create Date: 2026-08-30 16:45:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e1f4a7c92b60"
down_revision: str | Sequence[str] | None = "d6b1e4f92a50"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("opening_signals") as batch_op:
        batch_op.create_unique_constraint(
            "uq_opening_signals_contact_place",
            ["contact_id", "place_name"],
        )


def downgrade() -> None:
    with op.batch_alter_table("opening_signals") as batch_op:
        batch_op.drop_constraint(
            "uq_opening_signals_contact_place",
            type_="unique",
        )
