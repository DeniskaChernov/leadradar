"""add confirmed catalog offer and sale snapshot foundation

Revision ID: f2a5b8d13c70
Revises: e1f4a7c92b60
Create Date: 2026-08-30 17:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2a5b8d13c70"
down_revision: str | Sequence[str] | None = "e1f4a7c92b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(
            sa.Column(
                "import_source",
                sa.String(length=32),
                nullable=False,
                server_default="SEED",
            )
        )
        batch_op.add_column(
            sa.Column(
                "catalog_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.add_column(sa.Column("category_confirmed_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("category_confirmed_by", sa.Integer()))
        batch_op.add_column(sa.Column("price_confirmed_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("price_confirmed_by", sa.Integer()))
        batch_op.add_column(sa.Column("stock_confirmed_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("stock_confirmed_by", sa.Integer()))
        batch_op.add_column(sa.Column("cogs_confirmed_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("cogs_confirmed_by", sa.Integer()))
    op.execute(
        sa.text(
            "UPDATE products SET price_confirmed_at = created_at "
            "WHERE price IS NOT NULL AND source_reference IS NOT NULL"
        )
    )

    with op.batch_alter_table("deals") as batch_op:
        batch_op.add_column(sa.Column("product_id", sa.Integer()))
        batch_op.create_foreign_key(
            "fk_deals_product_id_products",
            "products",
            ["product_id"],
            ["id"],
        )
        batch_op.create_index("ix_deals_product_id", ["product_id"])

    op.create_table(
        "product_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("change_type", sa.String(length=32), nullable=False),
        sa.Column("manager_telegram_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=False),
        sa.Column("after_json", sa.JSON(), nullable=False),
        sa.Column("catalog_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_product_changes_product_id", "product_changes", ["product_id"])
    op.create_index("ix_product_changes_change_type", "product_changes", ["change_type"])
    op.create_index(
        "ix_product_changes_manager_telegram_id",
        "product_changes",
        ["manager_telegram_id"],
    )

    op.create_table(
        "deal_sale_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_id", sa.Integer(), sa.ForeignKey("deals.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id")),
        sa.Column("product_canonical_key", sa.String(length=255)),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("sku", sa.String(length=128)),
        sa.Column("category", sa.String(length=64)),
        sa.Column("catalog_price", sa.Numeric(14, 2)),
        sa.Column("catalog_currency", sa.String(length=8)),
        sa.Column("cogs", sa.Numeric(14, 2)),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("sale_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("sale_currency", sa.String(length=8), nullable=False),
        sa.Column("catalog_version", sa.Integer()),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("manager_telegram_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("deal_id", name="uq_deal_sale_snapshots_deal_id"),
    )
    op.create_index("ix_deal_sale_snapshots_deal_id", "deal_sale_snapshots", ["deal_id"])
    op.create_index("ix_deal_sale_snapshots_product_id", "deal_sale_snapshots", ["product_id"])


def downgrade() -> None:
    op.drop_table("deal_sale_snapshots")
    op.drop_table("product_changes")
    with op.batch_alter_table("deals") as batch_op:
        batch_op.drop_index("ix_deals_product_id")
        batch_op.drop_constraint("fk_deals_product_id_products", type_="foreignkey")
        batch_op.drop_column("product_id")
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_column("cogs_confirmed_by")
        batch_op.drop_column("cogs_confirmed_at")
        batch_op.drop_column("stock_confirmed_by")
        batch_op.drop_column("stock_confirmed_at")
        batch_op.drop_column("category_confirmed_by")
        batch_op.drop_column("category_confirmed_at")
        batch_op.drop_column("price_confirmed_by")
        batch_op.drop_column("price_confirmed_at")
        batch_op.drop_column("catalog_version")
        batch_op.drop_column("import_source")
