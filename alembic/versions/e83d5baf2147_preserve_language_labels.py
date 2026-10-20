"""Preserve existing language labels during PostgreSQL restores.

SQLite does not enforce VARCHAR length; existing provider labels can exceed 16
characters. Keep them intact rather than truncate historical lead data.
"""

import sqlalchemy as sa

from alembic import op

revision = "e83d5baf2147"
down_revision = "d72c4a9e1036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("leads", "language", existing_type=sa.String(16), type_=sa.Text())


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    if connection.scalar(sa.text("SELECT count(*) FROM leads WHERE length(language) > 16")):
        raise RuntimeError("Cannot narrow language labels without losing existing values")
    op.alter_column("leads", "language", existing_type=sa.Text(), type_=sa.String(16))
