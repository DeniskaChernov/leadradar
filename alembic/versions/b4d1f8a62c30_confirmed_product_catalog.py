"""confirmed product catalog

Revision ID: b4d1f8a62c30
Revises: a7c9e2f51d40
Create Date: 2026-08-28 20:30:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4d1f8a62c30"
down_revision: str | Sequence[str] | None = "a7c9e2f51d40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_key", sa.String(length=255), nullable=False),
        sa.Column("sku", sa.String(length=128), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("vertical", sa.String(length=32), nullable=False, server_default="FURNITURE"),
        sa.Column("category", sa.String(length=64), nullable=False, server_default="UNCONFIRMED"),
        sa.Column("price", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("cogs", sa.Numeric(14, 2), nullable=True),
        sa.Column("stock", sa.Integer(), nullable=True),
        sa.Column("minimum_order_quantity", sa.Integer(), nullable=True),
        sa.Column("dimensions_json", sa.JSON(), nullable=True),
        sa.Column("colors_json", sa.JSON(), nullable=False),
        sa.Column("max_load_kg", sa.Numeric(10, 2), nullable=True),
        sa.Column("b2b_suitability", sa.String(length=32), nullable=False, server_default="UNCONFIRMED"),
        sa.Column("photo_url", sa.Text(), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("canonical_key", name="uq_products_canonical_key"),
        sa.UniqueConstraint("sku", name="uq_products_sku"),
    )
    op.create_index("ix_products_canonical_key", "products", ["canonical_key"], unique=True)
    op.create_index("ix_products_sku", "products", ["sku"], unique=True)
    op.create_index("ix_products_name", "products", ["name"])
    op.create_index("ix_products_vertical", "products", ["vertical"])
    op.create_index("ix_products_category", "products", ["category"])
    op.create_index("ix_products_active", "products", ["active"])


def downgrade() -> None:
    op.drop_index("ix_products_active", table_name="products")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_index("ix_products_vertical", table_name="products")
    op.drop_index("ix_products_name", table_name="products")
    op.drop_index("ix_products_sku", table_name="products")
    op.drop_index("ix_products_canonical_key", table_name="products")
    op.drop_table("products")
