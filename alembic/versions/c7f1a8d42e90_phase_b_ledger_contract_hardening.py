"""harden Phase B AI and budget ledgers

Revision ID: c7f1a8d42e90
Revises: a6d4e2c91f30
Create Date: 2026-08-28 11:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7f1a8d42e90"
down_revision: str | Sequence[str] | None = "a6d4e2c91f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ai_requests") as batch:
        batch.alter_column(
            "analysis_version",
            existing_type=sa.Integer(),
            type_=sa.String(length=32),
            existing_nullable=False,
            server_default="3.0",
        )
        batch.add_column(sa.Column("prompt_version", sa.String(length=32)))
        batch.add_column(sa.Column("schema_version", sa.String(length=32)))
        batch.add_column(sa.Column("error_type", sa.String(length=128)))
        batch.add_column(sa.Column("error_message", sa.Text()))
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE ai_requests SET analysis_version = '3.0' WHERE analysis_version = '3'")
    op.execute("UPDATE ai_requests SET prompt_version = 'lead-v3' WHERE prompt_version IS NULL")
    op.execute(
        "UPDATE ai_requests SET schema_version = 'lead-analysis-v3' WHERE schema_version IS NULL"
    )
    with op.batch_alter_table("ai_requests") as batch:
        batch.alter_column("prompt_version", existing_type=sa.String(length=32), nullable=False)
        batch.alter_column("schema_version", existing_type=sa.String(length=32), nullable=False)

    with op.batch_alter_table("external_budget_reservations") as batch:
        batch.add_column(sa.Column("reservation_key", sa.String(length=128)))
        batch.add_column(sa.Column("worker_id", sa.String(length=128)))
        batch.add_column(sa.Column("reserved_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("call_started_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("released_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("actual_units", sa.Integer()))
        batch.add_column(sa.Column("actual_cost_usd", sa.Numeric(10, 6)))
        batch.add_column(sa.Column("details_json", sa.JSON()))
    op.execute(
        "UPDATE external_budget_reservations "
        "SET reservation_key = 'legacy:' || id, reserved_at = created_at, details_json = '{}' "
        "WHERE reservation_key IS NULL"
    )
    with op.batch_alter_table("external_budget_reservations") as batch:
        batch.alter_column(
            "reservation_key", existing_type=sa.String(length=128), nullable=False
        )
        batch.alter_column("reserved_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.alter_column("details_json", existing_type=sa.JSON(), nullable=False)
        batch.create_index(
            "ix_external_budget_reservations_reservation_key",
            ["reservation_key"],
            unique=True,
        )
        batch.create_index(
            "ix_external_budget_reservations_worker_id", ["worker_id"], unique=False
        )
        batch.create_index(
            "ix_external_budget_reservations_reserved_at", ["reserved_at"], unique=False
        )

    with op.batch_alter_table("external_usage") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(length=128)))
        batch.create_index(
            "ix_external_usage_idempotency_key", ["idempotency_key"], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table("external_usage") as batch:
        batch.drop_index("ix_external_usage_idempotency_key")
        batch.drop_column("idempotency_key")
    with op.batch_alter_table("external_budget_reservations") as batch:
        batch.drop_index("ix_external_budget_reservations_reserved_at")
        batch.drop_index("ix_external_budget_reservations_worker_id")
        batch.drop_index("ix_external_budget_reservations_reservation_key")
        for column in (
            "details_json",
            "actual_cost_usd",
            "actual_units",
            "released_at",
            "call_started_at",
            "reserved_at",
            "worker_id",
            "reservation_key",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("ai_requests") as batch:
        batch.drop_column("completed_at")
        batch.drop_column("error_message")
        batch.drop_column("error_type")
        batch.drop_column("schema_version")
        batch.drop_column("prompt_version")
        batch.alter_column(
            "analysis_version",
            existing_type=sa.String(length=32),
            type_=sa.Integer(),
            existing_nullable=False,
            server_default="1",
        )
