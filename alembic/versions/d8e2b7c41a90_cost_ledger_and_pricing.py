"""add attributable cost ledger and versioned pricing

Revision ID: d8e2b7c41a90
Revises: c7f1a8d42e90
Create Date: 2026-08-28 14:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d8e2b7c41a90"
down_revision: str | Sequence[str] | None = "c7f1a8d42e90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    old_status = sa.Enum(
        "RESERVED", "FINALIZED", "RELEASED", "EXPIRED",
        name="reservationstatus", native_enum=False,
    )
    new_status = sa.Enum(
        "RESERVED", "FINALIZED", "RELEASED", "EXPIRED", "UNCERTAIN",
        name="reservationstatus", native_enum=False,
    )
    with op.batch_alter_table("external_budget_reservations") as batch:
        batch.add_column(sa.Column("provider", sa.String(length=128)))
        batch.alter_column(
            "status",
            existing_type=old_status,
            type_=new_status,
            existing_nullable=False,
        )
    op.execute(
        "UPDATE external_budget_reservations SET provider = lower(service) "
        "WHERE provider IS NULL"
    )
    with op.batch_alter_table("external_budget_reservations") as batch:
        batch.alter_column("provider", existing_type=sa.String(length=128), nullable=False)
        batch.create_index(
            "ix_external_budget_reservations_provider", ["provider"], unique=False
        )

    op.create_table(
        "pricing_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("pricing_basis", sa.String(length=32), nullable=False),
        sa.Column("input_price", sa.Numeric(14, 8)),
        sa.Column("output_price", sa.Numeric(14, 8)),
        sa.Column("unit_price", sa.Numeric(14, 8)),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "operation", "model_name", "effective_from",
            name="uq_pricing_configs_provider_operation_model_effective",
        ),
    )
    for column in (
        "provider", "operation", "model_name", "effective_from", "active", "created_at"
    ):
        op.create_index(f"ix_pricing_configs_{column}", "pricing_configs", [column])

    vertical = sa.Enum(
        "FURNITURE", "ARTIFICIAL_RATTAN", name="vertical", native_enum=False
    )
    op.create_table(
        "cost_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("reservation_id", sa.Integer()),
        sa.Column("service", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("vertical", vertical),
        sa.Column("competitor_id", sa.Integer()),
        sa.Column("lead_id", sa.Integer()),
        sa.Column("audience_id", sa.Integer()),
        sa.Column("campaign_id", sa.Integer()),
        sa.Column("units", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("cost_usd", sa.Numeric(12, 6)),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["reservation_id"], ["external_budget_reservations.id"]),
        sa.ForeignKeyConstraint(["competitor_id"], ["competitors.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.ForeignKeyConstraint(["audience_id"], ["audience_segments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "idempotency_key", "reservation_id", "service", "provider", "operation",
        "vertical", "competitor_id", "lead_id", "audience_id", "campaign_id", "created_at",
    ):
        op.create_index(
            f"ix_cost_events_{column}",
            "cost_events",
            [column],
            unique=column in {"idempotency_key", "reservation_id"},
        )


def downgrade() -> None:
    op.drop_table("cost_events")
    op.drop_table("pricing_configs")
    old_status = sa.Enum(
        "RESERVED", "FINALIZED", "RELEASED", "EXPIRED",
        name="reservationstatus", native_enum=False,
    )
    new_status = sa.Enum(
        "RESERVED", "FINALIZED", "RELEASED", "EXPIRED", "UNCERTAIN",
        name="reservationstatus", native_enum=False,
    )
    with op.batch_alter_table("external_budget_reservations") as batch:
        batch.drop_index("ix_external_budget_reservations_provider")
        batch.drop_column("provider")
        batch.alter_column(
            "status",
            existing_type=new_status,
            type_=old_status,
            existing_nullable=False,
        )
