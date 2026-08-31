"""Reset auto-promoted rattan portfolio membership.

Revision ID: f1a8c3e74b90
Revises: e4f7a1c93b20

Competitor.vertical is the enrollment flag for the rattan portfolio.
Previously taxonomy rebuild could flip furniture sources into ARTIFICIAL_RATTAN
without an explicit operator action. This repair restores FURNITURE membership;
operators re-enroll rattan sources via UI.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a8c3e74b90"
down_revision: str | Sequence[str] | None = "e4f7a1c93b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE competitors SET vertical = 'FURNITURE' "
            "WHERE vertical = 'ARTIFICIAL_RATTAN'"
        )
    )


def downgrade() -> None:
    # Необратимо: исходный auto-promote список не сохранялся.
    pass
