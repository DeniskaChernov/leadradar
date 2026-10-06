"""Persist comment backfill position and serialize outreach generation."""

import sqlalchemy as sa

from alembic import op

revision = "f6b7c8d9e0a1"
down_revision = "e5a6b7c8d9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("comment_backfill_cursor", sa.Text(), nullable=True))
    op.add_column("posts", sa.Column("comment_backfill_provider", sa.String(128), nullable=True))
    op.add_column("posts", sa.Column("comment_backfill_is_baseline", sa.Boolean(), nullable=True))
    op.add_column("posts", sa.Column("comment_backfill_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("outreach_claim_token", sa.String(64), nullable=True))
    op.add_column("leads", sa.Column("outreach_claim_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    active = op.get_bind().scalar(sa.text(
        "SELECT COUNT(*) FROM leads WHERE outreach_claim_token IS NOT NULL"
    ))
    if active:
        raise RuntimeError("Resolve outstanding outreach claims before downgrade")
    with op.batch_alter_table("leads") as batch:
        batch.drop_column("outreach_claim_expires_at")
        batch.drop_column("outreach_claim_token")
    with op.batch_alter_table("posts") as batch:
        batch.drop_column("comment_backfill_completed_at")
        batch.drop_column("comment_backfill_is_baseline")
        batch.drop_column("comment_backfill_provider")
        batch.drop_column("comment_backfill_cursor")
