"""Persisted chat sessions для grounded agent."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AgentChatMessage, AgentChatSession


class AgentChatService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def create_session(
        self,
        manager_telegram_id: int,
        *,
        title: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentChatSession:
        now = datetime.now(UTC)
        row = AgentChatSession(
            manager_telegram_id=manager_telegram_id,
            title=(title or "").strip() or None,
            context_json=dict(context or {}),
            created_at=now,
            updated_at=now,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get_session(self, session_id: int) -> AgentChatSession | None:
        async with self.session_factory() as session:
            return await session.get(AgentChatSession, session_id)

    async def list_sessions(
        self,
        manager_telegram_id: int,
        *,
        limit: int = 30,
    ) -> list[AgentChatSession]:
        limit = max(1, min(limit, 100))
        async with self.session_factory() as session:
            return list(
                await session.scalars(
                    select(AgentChatSession)
                    .where(AgentChatSession.manager_telegram_id == manager_telegram_id)
                    .order_by(desc(AgentChatSession.updated_at), desc(AgentChatSession.id))
                    .limit(limit)
                )
            )

    async def list_messages(self, session_id: int, *, limit: int = 100) -> list[AgentChatMessage]:
        limit = max(1, min(limit, 500))
        async with self.session_factory() as session:
            return list(
                await session.scalars(
                    select(AgentChatMessage)
                    .where(AgentChatMessage.session_id == session_id)
                    .order_by(AgentChatMessage.id)
                    .limit(limit)
                )
            )

    async def append_message(
        self,
        session_id: int,
        *,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        pending_action: dict[str, Any] | None = None,
        evidence_ids: list[int] | None = None,
    ) -> AgentChatMessage:
        now = datetime.now(UTC)
        row = AgentChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            tool_calls_json=list(tool_calls or []),
            pending_action_json=dict(pending_action) if pending_action else None,
            pending_status="pending" if pending_action else None,
            evidence_ids_json=list(evidence_ids or []),
            created_at=now,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.execute(
                update(AgentChatSession)
                .where(AgentChatSession.id == session_id)
                .values(updated_at=now)
            )
            await session.commit()
            await session.refresh(row)
            return row

    async def get_message(self, message_id: int) -> AgentChatMessage | None:
        async with self.session_factory() as session:
            return await session.get(AgentChatMessage, message_id)

    async def mark_pending_executed(
        self,
        message_id: int,
        *,
        tool_calls: list[dict[str, Any]],
        content_append: str,
    ) -> AgentChatMessage | None:
        async with self.session_factory() as session:
            row = await session.get(AgentChatMessage, message_id)
            if row is None or row.pending_status != "pending":
                return None
            row.pending_status = "executed"
            row.tool_calls_json = list(tool_calls)
            if content_append.strip():
                row.content = f"{row.content.rstrip()}\n\n{content_append.strip()}"
            await session.commit()
            await session.refresh(row)
            return row
