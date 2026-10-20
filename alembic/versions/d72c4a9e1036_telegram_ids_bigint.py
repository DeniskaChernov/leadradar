"""Store Telegram identities without PostgreSQL 32-bit overflow.

SQLite INTEGER already stores signed 64-bit values; do not rebuild its history
tables just to change a type spelling.
"""

import sqlalchemy as sa

from alembic import op

revision = "d72c4a9e1036"
down_revision = "ca219b748d30"
branch_labels = None
depends_on = None

COLUMNS = {
    "products": ("category_confirmed_by", "price_confirmed_by", "stock_confirmed_by", "cogs_confirmed_by"),
    "product_changes": ("manager_telegram_id",),
    "contacts": ("assigned_manager_telegram_id",),
    "leads": ("assigned_manager_telegram_id",),
    "deals": ("manager_telegram_id",),
    "deal_sale_snapshots": ("manager_telegram_id",),
    "contact_events": ("manager_telegram_id",),
    "notification_logs": ("chat_id",),
    "significant_change_notifications": ("chat_id",),
    "opening_signals": ("reviewed_by_manager_id",),
    "fx_rate_policies": ("manager_telegram_id",),
    "agent_chat_sessions": ("manager_telegram_id",),
}


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, columns in COLUMNS.items():
        for column in columns:
            op.alter_column(table, column, existing_type=sa.Integer(), type_=sa.BigInteger())


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    # Refuse a destructive narrowing before changing any column.
    for table, columns in COLUMNS.items():
        for column in columns:
            if connection.scalar(sa.text(
                f'SELECT count(*) FROM "{table}" WHERE "{column}" < -2147483648 OR "{column}" > 2147483647'
            )):
                raise RuntimeError("Cannot narrow Telegram identities without losing existing values")
    for table, columns in COLUMNS.items():
        for column in columns:
            op.alter_column(table, column, existing_type=sa.BigInteger(), type_=sa.Integer())
