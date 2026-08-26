"""normalize unique constraint names

Revision ID: 6a7b92dce104
Revises: 3d8f5e77a021
Create Date: 2026-08-26 15:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6a7b92dce104"
down_revision: str | Sequence[str] | None = "3d8f5e77a021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("contacts") as batch_op:
        batch_op.drop_constraint("uq_contacts_platform", type_="unique")
        batch_op.create_unique_constraint(
            "uq_contacts_platform_user_id", ["platform", "platform_user_id"]
        )
        batch_op.create_unique_constraint(
            "uq_contacts_platform_username", ["platform", "normalized_username"]
        )
    with op.batch_alter_table("comments") as batch_op:
        batch_op.drop_constraint("uq_comments_platform", type_="unique")
        batch_op.create_unique_constraint(
            "uq_comments_platform_comment_id", ["platform", "platform_comment_id"]
        )
    notification_status = sa.Enum(
        "PENDING",
        "PROCESSING",
        "SENT",
        "FAILED",
        name="notificationstatus",
        native_enum=False,
    )
    with op.batch_alter_table("notification_logs") as batch_op:
        batch_op.drop_constraint("uq_notification_logs_lead_id", type_="unique")
        batch_op.create_unique_constraint(
            "uq_notification_logs_lead_chat", ["lead_id", "chat_id"]
        )
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=7),
            type_=notification_status,
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("notification_logs") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.Enum(
                "PENDING",
                "PROCESSING",
                "SENT",
                "FAILED",
                name="notificationstatus",
                native_enum=False,
            ),
            type_=sa.String(length=7),
            existing_nullable=False,
        )
        batch_op.drop_constraint("uq_notification_logs_lead_chat", type_="unique")
        batch_op.create_unique_constraint(
            "uq_notification_logs_lead_id", ["lead_id", "chat_id"]
        )
    with op.batch_alter_table("comments") as batch_op:
        batch_op.drop_constraint("uq_comments_platform_comment_id", type_="unique")
        batch_op.create_unique_constraint(
            "uq_comments_platform", ["platform", "platform_comment_id"]
        )
    with op.batch_alter_table("contacts") as batch_op:
        batch_op.drop_constraint("uq_contacts_platform_username", type_="unique")
        batch_op.drop_constraint("uq_contacts_platform_user_id", type_="unique")
        batch_op.create_unique_constraint(
            "uq_contacts_platform", ["platform", "normalized_username"]
        )
        batch_op.create_unique_constraint(
            "uq_contacts_platform", ["platform", "platform_user_id"]
        )
