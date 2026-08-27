"""opening_signals — Phase 10 Google Future Openings & Place Resolution

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-08-27

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "opening_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("place_name", sa.String(length=255), nullable=False),
        sa.Column("place_type", sa.String(length=64), nullable=False, server_default="OTHER"),
        sa.Column("city", sa.String(length=128), nullable=False, server_default="Tashkent"),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("opening_timeline", sa.String(length=128), nullable=True),
        sa.Column("google_place_id", sa.String(length=255), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("source_type", sa.String(length=64), nullable=False, server_default="INSTAGRAM_PUBLIC_SIGNAL"),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("contacts.id"), nullable=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column("reviewed_by_manager_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("opening_signals", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_opening_signals_place_name"), ["place_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_opening_signals_review_status"), ["review_status"], unique=False)
        batch_op.create_index(batch_op.f("ix_opening_signals_contact_id"), ["contact_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("opening_signals", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_opening_signals_contact_id"))
        batch_op.drop_index(batch_op.f("ix_opening_signals_review_status"))
        batch_op.drop_index(batch_op.f("ix_opening_signals_place_name"))
    op.drop_table("opening_signals")
