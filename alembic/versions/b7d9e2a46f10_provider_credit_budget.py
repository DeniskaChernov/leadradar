"""Добавить бюджет провайдера, credit wallet и факты бюджета запусков.

Revision ID: b7d9e2a46f10
Revises: a3c8f7d24e10
"""

import sqlalchemy as sa

from alembic import op

revision = "b7d9e2a46f10"
down_revision = "a3c8f7d24e10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("monitor_runs") as batch:
        batch.add_column(sa.Column("requested_credit_budget", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("effective_credit_budget", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "actual_credits_spent",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(sa.Column("provider_balance_before", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("provider_balance_after", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("monthly_used_before", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("monthly_used_after", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("budget_stop_reason", sa.String(255), nullable=True))
        batch.add_column(
            sa.Column("operations_json", sa.JSON(), nullable=False, server_default="{}")
        )
        batch.add_column(sa.Column("adaptive_policy_version", sa.String(64), nullable=True))

    with op.batch_alter_table("external_usage") as batch:
        batch.add_column(
            sa.Column(
                "unit_source",
                sa.String(32),
                nullable=False,
                server_default="ESTIMATED",
            )
        )
        batch.create_index("ix_external_usage_unit_source", ["unit_source"], unique=False)

    with op.batch_alter_table("cost_events") as batch:
        batch.add_column(
            sa.Column(
                "unit_source",
                sa.String(32),
                nullable=False,
                server_default="ESTIMATED",
            )
        )
        batch.create_index("ix_cost_events_unit_source", ["unit_source"], unique=False)

    op.create_table(
        "provider_budget_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("service", sa.String(64), nullable=False),
        sa.Column("monthly_target_units", sa.Integer(), nullable=False),
        sa.Column("monthly_soft_limit_units", sa.Integer(), nullable=False),
        sa.Column("monthly_hard_limit_units", sa.Integer(), nullable=False),
        sa.Column("default_scan_budget_units", sa.Integer(), nullable=False),
        sa.Column("maximum_manual_scan_budget_units", sa.Integer(), nullable=False),
        sa.Column("target_minimum_months", sa.Integer(), nullable=False),
        sa.Column("comments_target_units", sa.Integer(), nullable=False),
        sa.Column("discovery_target_units", sa.Integer(), nullable=False),
        sa.Column("enrichment_target_units", sa.Integer(), nullable=False),
        sa.Column("reserve_target_units", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("manager_confirmed_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "provider",
            "service",
            name="uq_provider_budget_policy_scope",
        ),
        sa.CheckConstraint(
            "monthly_target_units >= 0 AND monthly_soft_limit_units >= monthly_target_units "
            "AND monthly_hard_limit_units >= monthly_soft_limit_units",
            name="ck_provider_budget_policy_monthly_limits",
        ),
        sa.CheckConstraint(
            "default_scan_budget_units > 0 "
            "AND maximum_manual_scan_budget_units >= default_scan_budget_units",
            name="ck_provider_budget_policy_scan_limits",
        ),
        sa.CheckConstraint(
            "comments_target_units >= 0 AND discovery_target_units >= 0 "
            "AND enrichment_target_units >= 0 AND reserve_target_units >= 0",
            name="ck_provider_budget_policy_allocations",
        ),
        sa.CheckConstraint(
            "target_minimum_months > 0",
            name="ck_provider_budget_policy_minimum_months",
        ),
    )
    op.create_index(
        "ix_provider_budget_policies_provider",
        "provider_budget_policies",
        ["provider"],
    )
    op.create_index(
        "ix_provider_budget_policies_service",
        "provider_budget_policies",
        ["service"],
    )
    op.create_index(
        "ix_provider_budget_policies_active",
        "provider_budget_policies",
        ["active"],
    )

    op.create_table(
        "provider_credit_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("credits_remaining", sa.Integer(), nullable=True),
        sa.Column("credits_charged", sa.Integer(), nullable=True),
        sa.Column("operation", sa.String(128), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("monitor_run_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["monitor_run_id"],
            ["monitor_runs.id"],
            name="fk_provider_credit_snapshots_monitor_run_id",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_provider_credit_snapshots_idempotency_key",
        ),
        sa.CheckConstraint(
            "credits_remaining IS NULL OR credits_remaining >= 0",
            name="ck_provider_credit_snapshot_remaining",
        ),
        sa.CheckConstraint(
            "credits_charged IS NULL OR credits_charged >= 0",
            name="ck_provider_credit_snapshot_charged",
        ),
    )
    op.create_index(
        "ix_provider_credit_snapshots_idempotency_key",
        "provider_credit_snapshots",
        ["idempotency_key"],
    )
    op.create_index(
        "ix_provider_credit_snapshots_provider",
        "provider_credit_snapshots",
        ["provider"],
    )
    op.create_index(
        "ix_provider_credit_snapshots_operation",
        "provider_credit_snapshots",
        ["operation"],
    )
    op.create_index(
        "ix_provider_credit_snapshots_source",
        "provider_credit_snapshots",
        ["source"],
    )
    op.create_index(
        "ix_provider_credit_snapshots_observed_at",
        "provider_credit_snapshots",
        ["observed_at"],
    )
    op.create_index(
        "ix_provider_credit_snapshots_monitor_run_id",
        "provider_credit_snapshots",
        ["monitor_run_id"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO provider_budget_policies (
                provider, service,
                monthly_target_units, monthly_soft_limit_units, monthly_hard_limit_units,
                default_scan_budget_units, maximum_manual_scan_budget_units,
                target_minimum_months,
                comments_target_units, discovery_target_units,
                enrichment_target_units, reserve_target_units,
                active, manager_confirmed_by
            ) VALUES (
                'scrapecreators', 'instagram',
                3000, 3500, 3800,
                10, 50,
                6,
                2400, 600, 200, 600,
                1, NULL
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_table("provider_credit_snapshots")
    op.drop_table("provider_budget_policies")

    with op.batch_alter_table("cost_events") as batch:
        batch.drop_index("ix_cost_events_unit_source")
        batch.drop_column("unit_source")

    with op.batch_alter_table("external_usage") as batch:
        batch.drop_index("ix_external_usage_unit_source")
        batch.drop_column("unit_source")

    with op.batch_alter_table("monitor_runs") as batch:
        batch.drop_column("adaptive_policy_version")
        batch.drop_column("operations_json")
        batch.drop_column("budget_stop_reason")
        batch.drop_column("monthly_used_after")
        batch.drop_column("monthly_used_before")
        batch.drop_column("provider_balance_after")
        batch.drop_column("provider_balance_before")
        batch.drop_column("actual_credits_spent")
        batch.drop_column("effective_credit_budget")
        batch.drop_column("requested_credit_budget")
