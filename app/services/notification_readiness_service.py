from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    Comment,
    Competitor,
    Lead,
    LeadStatus,
    NotificationLog,
    NotificationPolicy,
    NotificationStatus,
)
from app.services.lead_workflow_service import LeadWorkflowService


@dataclass(frozen=True, slots=True)
class NotificationPreview:
    lead_id: int
    contact_id: int
    username: str
    competitor: str
    comment: str
    score: int
    intent: str
    policy: str
    decision: str
    reason: str
    target_count: int
    idempotency_pattern: str


@dataclass(frozen=True, slots=True)
class NotificationReadinessReport:
    token_configured: bool
    delivery_allowed_by_config: bool
    worker_active: bool
    admin_target_count: int
    total_reviewed: int
    eligible: int
    queued: int
    sent: int
    suppressed: int
    blocked: int
    failed: int
    uncertain: int
    previews: tuple[NotificationPreview, ...]

    @property
    def controlled_pilot_ready(self) -> bool:
        return (
            self.token_configured
            and self.delivery_allowed_by_config
            and self.worker_active
            and self.admin_target_count > 0
            and self.uncertain == 0
        )


class NotificationReadinessService:
    """Build a read-only preview of Telegram delivery decisions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        workflow: LeadWorkflowService,
        *,
        admin_chat_ids: list[int],
        default_policy: NotificationPolicy,
        hot_threshold: int,
        token_configured: bool,
        delivery_allowed_by_config: bool,
        worker_active: bool,
    ) -> None:
        self.session_factory = session_factory
        self.workflow = workflow
        self.admin_chat_ids = list(dict.fromkeys(admin_chat_ids))
        self.default_policy = default_policy
        self.hot_threshold = hot_threshold
        self.token_configured = token_configured
        self.delivery_allowed_by_config = delivery_allowed_by_config
        self.worker_active = worker_active

    async def preview(self, *, limit: int = 10) -> NotificationReadinessReport:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        Lead.id,
                        Lead.assigned_manager_telegram_id,
                        Comment.is_baseline,
                        Competitor.notification_policy,
                    )
                    .join(Comment, Comment.id == Lead.comment_id)
                    .join(Competitor, Competitor.id == Lead.competitor_id)
                    .order_by(desc(Lead.created_at), desc(Lead.id))
                    .limit(max(1, min(limit, 50)))
                )
            ).all()
            lead_ids = [int(row.id) for row in rows]
            logs = list(
                await session.scalars(
                    select(NotificationLog)
                    .where(NotificationLog.lead_id.in_(lead_ids))
                    .order_by(desc(NotificationLog.updated_at), desc(NotificationLog.id))
                )
            )

        logs_by_lead: dict[int, list[NotificationLog]] = {}
        for log in logs:
            logs_by_lead.setdefault(log.lead_id, []).append(log)

        previews: list[NotificationPreview] = []
        for row in rows:
            card = await self.workflow.get_lead_card(int(row.id))
            policy = row.notification_policy or self.default_policy
            target_count = 1 if row.assigned_manager_telegram_id else len(self.admin_chat_ids)
            decision, reason = self._decision(
                card.status,
                card.score,
                bool(row.is_baseline),
                policy,
                target_count,
                logs_by_lead.get(card.lead_id, []),
            )
            previews.append(
                NotificationPreview(
                    lead_id=card.lead_id,
                    contact_id=card.contact_id,
                    username=card.username,
                    competitor=card.competitor,
                    comment=card.comment[:180],
                    score=card.score,
                    intent=card.intent,
                    policy=policy.value,
                    decision=decision,
                    reason=reason,
                    target_count=target_count,
                    idempotency_pattern=f"lead:{card.lead_id}:chat:*",
                )
            )

        counts = {
            key: sum(item.decision == key for item in previews)
            for key in (
                "ELIGIBLE",
                "QUEUED",
                "SENT",
                "SUPPRESSED",
                "BLOCKED",
                "FAILED",
                "UNCERTAIN",
            )
        }
        return NotificationReadinessReport(
            token_configured=self.token_configured,
            delivery_allowed_by_config=self.delivery_allowed_by_config,
            worker_active=self.worker_active,
            admin_target_count=len(self.admin_chat_ids),
            total_reviewed=len(previews),
            eligible=counts["ELIGIBLE"],
            queued=counts["QUEUED"],
            sent=counts["SENT"],
            suppressed=counts["SUPPRESSED"],
            blocked=counts["BLOCKED"],
            failed=counts["FAILED"],
            uncertain=counts["UNCERTAIN"],
            previews=tuple(previews),
        )

    def _decision(
        self,
        status: LeadStatus,
        score: int,
        is_baseline: bool,
        policy: NotificationPolicy,
        target_count: int,
        logs: list[NotificationLog],
    ) -> tuple[str, str]:
        log_statuses = {log.status for log in logs}
        if NotificationStatus.UNCERTAIN in log_statuses:
            return "UNCERTAIN", "Сетевой результат неоднозначен — требуется ручная сверка."
        if NotificationStatus.FAILED in log_statuses:
            return "FAILED", "Предыдущая доставка завершилась подтверждённой ошибкой."
        if log_statuses & {NotificationStatus.PENDING, NotificationStatus.PROCESSING}:
            return "QUEUED", "Outbox уже создан; повторный preview не создаёт новую запись."
        if NotificationStatus.SENT in log_statuses:
            return "SENT", "Сообщение уже подтверждено Telegram и повторно не отправится."
        if is_baseline:
            return "SUPPRESSED", "Исторический baseline не создаёт production-уведомление."
        if target_count == 0:
            return "BLOCKED", "Не назначен менеджер и не настроен admin chat."
        if policy == NotificationPolicy.ALL_NEW_COMMENTS:
            return "ELIGIBLE", "Новый уникальный сигнал подходит под текущую политику."
        if status in {LeadStatus.ANALYZING, LeadStatus.AI_PENDING}:
            return "SUPPRESSED", "Ожидается завершение локальной классификации."
        if policy == NotificationPolicy.COMMERCIAL_ONLY:
            if status != LeadStatus.NOT_LEAD:
                return "ELIGIBLE", "Локальная классификация подтвердила коммерческий интерес."
            return "SUPPRESSED", "Сигнал классифицирован как некоммерческий."
        if status != LeadStatus.NOT_LEAD and score >= self.hot_threshold:
            return "ELIGIBLE", f"Лид достиг HOT-порога {self.hot_threshold}."
        return "SUPPRESSED", f"Лид не достиг HOT-порога {self.hot_threshold}."
