"""meta activation foundation

Revision ID: d6b1e4f92a50
Revises: c5a9f2e81d40
Create Date: 2026-08-29 13:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d6b1e4f92a50"
down_revision: str | Sequence[str] | None = "c5a9f2e81d40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meta_audience_blueprints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "audience_definition_id",
            sa.Integer(),
            sa.ForeignKey("audience_segments.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("eligibility_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("first_party_required", sa.Boolean(), nullable=False),
        sa.Column("minimum_seed_size", sa.Integer(), nullable=False),
        sa.Column("data_requirements_json", sa.JSON(), nullable=False),
        sa.Column("suggested_geo_json", sa.JSON(), nullable=False),
        sa.Column("suggested_interests_json", sa.JSON(), nullable=False),
        sa.Column("suggested_exclusions_json", sa.JSON(), nullable=False),
        sa.Column("suggested_broadness", sa.String(16), nullable=False),
        sa.Column("meta_catalog_version", sa.String(64)),
        sa.Column("last_validated_at", sa.DateTime(timezone=True)),
        sa.Column("engine_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "audience_definition_id", "mode", name="uq_meta_blueprint_definition_mode"
        ),
    )
    op.create_index(
        "ix_meta_audience_blueprints_audience_definition_id",
        "meta_audience_blueprints",
        ["audience_definition_id"],
    )
    op.create_index("ix_meta_audience_blueprints_mode", "meta_audience_blueprints", ["mode"])
    op.create_index(
        "ix_meta_audience_blueprints_eligibility_status",
        "meta_audience_blueprints",
        ["eligibility_status"],
    )
    op.create_table(
        "meta_interests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("meta_interest_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("path_json", sa.JSON(), nullable=False),
        sa.Column("audience_size", sa.Integer()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deprecated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("meta_interest_id", name="uq_meta_interests_meta_interest_id"),
    )
    op.create_index(
        "ix_meta_interests_meta_interest_id", "meta_interests", ["meta_interest_id"], unique=True
    )
    op.create_index("ix_meta_interests_status", "meta_interests", ["status"])
    op.create_table(
        "meta_interest_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("internal_topic", sa.String(128), nullable=False),
        sa.Column(
            "meta_interest_id",
            sa.String(128),
            sa.ForeignKey("meta_interests.meta_interest_id"),
            nullable=False,
        ),
        sa.Column("mapping_score", sa.Integer(), nullable=False),
        sa.Column("mapping_reason", sa.Text(), nullable=False),
        sa.Column("mapping_version", sa.String(32), nullable=False),
        sa.Column("validated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "internal_topic",
            "meta_interest_id",
            "mapping_version",
            name="uq_meta_interest_mapping_scope",
        ),
    )
    op.create_index(
        "ix_meta_interest_mappings_internal_topic", "meta_interest_mappings", ["internal_topic"]
    )
    op.create_index(
        "ix_meta_interest_mappings_meta_interest_id", "meta_interest_mappings", ["meta_interest_id"]
    )
    op.create_index("ix_meta_interest_mappings_validated", "meta_interest_mappings", ["validated"])
    op.create_table(
        "meta_targeting_recipes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "blueprint_id",
            sa.Integer(),
            sa.ForeignKey("meta_audience_blueprints.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("objective", sa.String(64), nullable=False),
        sa.Column("strategy", sa.String(16), nullable=False),
        sa.Column("geo_json", sa.JSON(), nullable=False),
        sa.Column("age_policy", sa.String(64), nullable=False),
        sa.Column("interest_ids_json", sa.JSON(), nullable=False),
        sa.Column("excluded_interest_ids_json", sa.JSON(), nullable=False),
        sa.Column("custom_audience_inclusions_json", sa.JSON(), nullable=False),
        sa.Column("custom_audience_exclusions_json", sa.JSON(), nullable=False),
        sa.Column("lookalike_seed", sa.String(255)),
        sa.Column("broad_targeting", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "blueprint_id", "strategy", "version", name="uq_meta_targeting_recipe_version"
        ),
    )
    op.create_index(
        "ix_meta_targeting_recipes_blueprint_id", "meta_targeting_recipes", ["blueprint_id"]
    )
    op.create_index("ix_meta_targeting_recipes_strategy", "meta_targeting_recipes", ["strategy"])
    op.create_index("ix_meta_targeting_recipes_status", "meta_targeting_recipes", ["status"])
    op.create_table(
        "meta_export_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "blueprint_id",
            sa.Integer(),
            sa.ForeignKey("meta_audience_blueprints.id"),
            nullable=False,
        ),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("eligibility_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "blueprint_id", "contact_id", name="uq_meta_export_candidate_blueprint_contact"
        ),
    )
    op.create_index(
        "ix_meta_export_candidates_blueprint_id", "meta_export_candidates", ["blueprint_id"]
    )
    op.create_index(
        "ix_meta_export_candidates_contact_id", "meta_export_candidates", ["contact_id"]
    )
    op.create_index(
        "ix_meta_export_candidates_eligibility_status",
        "meta_export_candidates",
        ["eligibility_status"],
    )
    op.create_table(
        "meta_audience_syncs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column(
            "blueprint_id",
            sa.Integer(),
            sa.ForeignKey("meta_audience_blueprints.id"),
            nullable=False,
        ),
        sa.Column("external_audience_id", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_meta_audience_syncs_idempotency_key"),
    )
    op.create_index(
        "ix_meta_audience_syncs_idempotency_key",
        "meta_audience_syncs",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index("ix_meta_audience_syncs_blueprint_id", "meta_audience_syncs", ["blueprint_id"])
    op.create_index("ix_meta_audience_syncs_status", "meta_audience_syncs", ["status"])


def downgrade() -> None:
    for table in (
        "meta_audience_syncs",
        "meta_export_candidates",
        "meta_targeting_recipes",
        "meta_interest_mappings",
        "meta_interests",
        "meta_audience_blueprints",
    ):
        op.drop_table(table)
