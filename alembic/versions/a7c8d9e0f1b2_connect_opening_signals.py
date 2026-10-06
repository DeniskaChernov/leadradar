"""Track opening extraction and allow an unknown venue city."""

import sqlalchemy as sa

from alembic import op

revision = "a7c8d9e0f1b2"
down_revision = "f6b7c8d9e0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("opening_checked_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("opening_signals") as batch:
        batch.alter_column("city", existing_type=sa.String(128), nullable=True)


def downgrade() -> None:
    # Empty string preserves unknown cities without inventing a location.
    op.execute("UPDATE opening_signals SET city = '' WHERE city IS NULL")
    with op.batch_alter_table("opening_signals") as batch:
        batch.alter_column("city", existing_type=sa.String(128), nullable=False)
    with op.batch_alter_table("leads") as batch:
        batch.drop_column("opening_checked_at")
