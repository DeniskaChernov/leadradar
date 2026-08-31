"""Normalize truncated/double-prefixed check constraint names.

Revision ID: d9e4b1c82a70
Revises: c8f3a1d57b20

PostgreSQL-only repair. Fresh installs already get canonical names from earlier
migrations after the ORM token shortening. SQLite keeps existing CHECKs; alembic
check ignores check-constraint name drift via env include_object.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "d9e4b1c82a70"
down_revision: str | Sequence[str] | None = "c8f3a1d57b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TARGETS: dict[str, tuple[tuple[str, str], ...]] = {
    "contact_interest_profiles": (
        ("ck_contact_interest_profiles_confidence", "confidence >= 0 AND confidence <= 100"),
        (
            "ck_contact_interest_profiles_current_score",
            "current_score >= 0 AND current_score <= 100",
        ),
    ),
    "provider_budget_policies": (
        (
            "ck_provider_budget_policies_monthly_limits",
            "monthly_target_units >= 0 AND monthly_soft_limit_units >= monthly_target_units "
            "AND monthly_hard_limit_units >= monthly_soft_limit_units",
        ),
        (
            "ck_provider_budget_policies_scan_limits",
            "default_scan_budget_units > 0 "
            "AND maximum_manual_scan_budget_units >= default_scan_budget_units",
        ),
        (
            "ck_provider_budget_policies_allocations",
            "comments_target_units >= 0 AND discovery_target_units >= 0 "
            "AND enrichment_target_units >= 0 AND reserve_target_units >= 0",
        ),
        (
            "ck_provider_budget_policies_minimum_months",
            "target_minimum_months > 0",
        ),
    ),
    "provider_credit_snapshots": (
        (
            "ck_provider_credit_snapshots_remaining",
            "credits_remaining IS NULL OR credits_remaining >= 0",
        ),
        (
            "ck_provider_credit_snapshots_charged",
            "credits_charged IS NULL OR credits_charged >= 0",
        ),
    ),
}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = inspect(bind)
    for table, desired in _TARGETS.items():
        existing = {
            item["name"]
            for item in inspector.get_check_constraints(table)
            if item.get("name")
        }
        desired_names = {name for name, _sql in desired}
        if existing == desired_names:
            continue
        for name in sorted(existing):
            op.execute(sa.text(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{name}"'))
        for name, sql in desired:
            op.execute(sa.text(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" CHECK ({sql})'))


def downgrade() -> None:
    pass
