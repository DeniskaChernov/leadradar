"""Persisted agent chat sessions and messages.

Revision ID: c4d5e6f7a8b9
Revises: a2b3c4d5e6f7
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | Sequence[str] | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("manager_telegram_id", sa.Integer(), nullable=False, index=True),
        sa.Column("title", sa.String(length=160), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
    )
    op.create_index("ix_agent_chat_sessions_created_at", "agent_chat_sessions", ["created_at"])
    op.create_index("ix_agent_chat_sessions_updated_at", "agent_chat_sessions", ["updated_at"])
    op.create_table(
        "agent_chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("agent_chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("role", sa.String(length=16), nullable=False, index=True),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_calls_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("pending_action_json", sa.JSON(), nullable=True),
        sa.Column("pending_status", sa.String(length=16), nullable=True, index=True),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_agent_chat_sessions_updated_at", table_name="agent_chat_sessions")
    op.drop_index("ix_agent_chat_sessions_created_at", table_name="agent_chat_sessions")
    op.drop_table("agent_chat_messages")
    op.drop_table("agent_chat_sessions")
