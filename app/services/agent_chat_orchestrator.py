"""Persistent agent chat: memory, read tools, approval-gated writes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.agent_chat_service import AgentChatService
from app.services.agent_session_service import AgentSessionService

_HANDLE_RE = re.compile(r"@?([a-zA-Z0-9][a-zA-Z0-9._]{1,62})", re.IGNORECASE)
_FILE_WRITE_RE = re.compile(
    r"(?:запиши|write|сохрани)\s+(?:в|to)\s+([^\s:]+)\s*:\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)
_COMPETITOR_WRITE_TOKENS = (
    "добавь конкурент",
    "add competitor",
    "новый конкурент",
    "включи мониторинг",
    "активируй конкурент",
)


@dataclass(frozen=True, slots=True)
class AgentChatTurnResult:
    session_id: int
    user_message_id: int
    assistant_message_id: int
    query: str
    answer: str
    evidence_ids: tuple[int, ...]
    tool_calls: tuple[dict[str, Any], ...]
    grounded: bool
    synthesis_mode: str
    pending_action: dict[str, Any] | None


class AgentChatOrchestrator:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        hot_threshold: int,
    ) -> None:
        self.chat = AgentChatService(session_factory)
        self.agent = AgentSessionService(session_factory, hot_threshold=hot_threshold)
        self.gateway = self.agent.gateway

    async def chat_turn(
        self,
        manager_telegram_id: int,
        query: str,
        *,
        session_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentChatTurnResult:
        normalized = (query or "").strip()
        if not normalized:
            raise ValueError("query is required")

        session = await self._resolve_session(session_id, manager_telegram_id, normalized)
        payload = dict(context or {})
        history = await self.chat.list_messages(session.id, limit=20)
        user_msg = await self.chat.append_message(session.id, role="user", content=normalized)

        write_plan = self._plan_write_action(normalized)
        if write_plan is not None:
            tool_name, arguments = write_plan
            answer = (
                f"Запрошено действие `{tool_name}` с параметрами {arguments}. "
                "Подтвердите выполнение — изменение применится только после approval."
            )
            assistant = await self.chat.append_message(
                session.id,
                role="assistant",
                content=answer,
                pending_action={"tool_name": tool_name, "arguments": arguments},
            )
            return AgentChatTurnResult(
                session_id=session.id,
                user_message_id=user_msg.id,
                assistant_message_id=assistant.id,
                query=normalized,
                answer=answer,
                evidence_ids=(),
                tool_calls=(),
                grounded=False,
                synthesis_mode="approval_pending",
                pending_action={"message_id": assistant.id, "tool_name": tool_name, "arguments": arguments},
            )

        result = await self.agent.query(normalized, context=payload)
        memory_hint = self._memory_hint(history)
        answer = result.answer
        if memory_hint:
            answer = f"{memory_hint}\n\n{answer}"

        tool_calls_payload = [
            {
                "tool_name": item.tool_name,
                "arguments": item.arguments,
                "success": item.result.success,
                "output": item.result.output,
            }
            for item in result.tool_calls
        ]
        assistant = await self.chat.append_message(
            session.id,
            role="assistant",
            content=answer,
            tool_calls=tool_calls_payload,
            evidence_ids=list(result.evidence_ids),
        )
        return AgentChatTurnResult(
            session_id=session.id,
            user_message_id=user_msg.id,
            assistant_message_id=assistant.id,
            query=result.query,
            answer=answer,
            evidence_ids=result.evidence_ids,
            tool_calls=tuple(tool_calls_payload),
            grounded=result.grounded,
            synthesis_mode=result.synthesis_mode,
            pending_action=None,
        )

    async def approve_pending(
        self,
        message_id: int,
        *,
        manager_telegram_id: int,
    ) -> dict[str, Any]:
        message = await self.chat.get_message(message_id)
        if message is None or message.pending_status != "pending":
            raise ValueError("pending action not found")
        session = await self.chat.get_session(message.session_id)
        if session is None or session.manager_telegram_id != manager_telegram_id:
            raise ValueError("session access denied")
        pending = message.pending_action_json or {}
        tool_name = str(pending.get("tool_name") or "")
        arguments = dict(pending.get("arguments") or {})
        if not tool_name:
            raise ValueError("invalid pending action")

        result = await self.gateway.execute_tool_async(
            tool_name,
            arguments,
            approval_granted=True,
        )
        tool_payload = [
            {
                "tool_name": tool_name,
                "arguments": arguments,
                "success": result.success,
                "output": result.output,
            }
        ]
        append = (
            f"✓ Выполнено: {tool_name}\n{result.output}"
            if result.success
            else f"✗ Ошибка: {result.output}"
        )
        updated = await self.chat.mark_pending_executed(
            message_id,
            tool_calls=tool_payload,
            content_append=append,
        )
        return {
            "ok": result.success,
            "message_id": message_id,
            "tool_name": tool_name,
            "output": result.output,
            "content": updated.content if updated else append,
        }

    async def _resolve_session(
        self,
        session_id: int | None,
        manager_telegram_id: int,
        title_hint: str,
    ):
        if session_id is not None:
            row = await self.chat.get_session(session_id)
            if row is None or row.manager_telegram_id != manager_telegram_id:
                raise ValueError("session not found")
            return row
        return await self.chat.create_session(
            manager_telegram_id,
            title=title_hint[:80],
        )

    @classmethod
    def _plan_write_action(cls, query: str) -> tuple[str, dict[str, Any]] | None:
        lowered = query.lower().strip()
        file_match = _FILE_WRITE_RE.search(query)
        if file_match:
            return (
                "project.write_file",
                {
                    "relative_path": file_match.group(1).strip(),
                    "content": file_match.group(2).strip(),
                    "mode": "append" if "допол" in lowered or "append" in lowered else "overwrite",
                },
            )
        if any(token in lowered for token in _COMPETITOR_WRITE_TOKENS):
            handle = cls._extract_handle(query)
            if handle:
                active = "выключ" not in lowered and "pause" not in lowered and "пауз" not in lowered
                tier = "A" if " tier a" in lowered or "приоритет a" in lowered else None
                return (
                    "competitor.manage",
                    {"handle": handle, "active": active, **({"tier": tier} if tier else {})},
                )
        return None

    @staticmethod
    def _extract_handle(query: str) -> str | None:
        for match in _HANDLE_RE.finditer(query):
            candidate = match.group(1).lower()
            if candidate not in {"id", "tier", "lead", "competitor"}:
                return candidate
        return None

    @staticmethod
    def _memory_hint(history: list) -> str:
        prior = [item.content.strip() for item in history if item.role == "user"][-3:]
        if len(prior) < 2:
            return ""
        return f"Контекст сессии ({len(prior)} сообщ.): «{' → '.join(prior)}»"
