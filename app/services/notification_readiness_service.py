from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    Comment,
    Competitor,
    Lead,
    LeadStatus,
    NotificationLog,
    NotificationPolicy,
    NotificationStatus,
    SignificantChangeNotification,
)
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.notification_eligibility import policy_decision
from app.services.signal_recency import is_signal_within_window, signal_observed_at


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
    total_uncertain: int = 0

    @property
    def delivery_active(self) -> bool:
        return (
            self.token_configured
            and self.delivery_allowed_by_config
            and self.worker_active
            and self.admin_target_count > 0
        )

    @property
    def controlled_pilot_ready(self) -> bool:
        return self.delivery_active and self.uncertain == 0 and self.total_uncertain == 0


class NotificationReadinessService:
    """Build a read-only preview of Telegram delivery decisions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        workflow: LeadWorkflowService,
        *,
        manager_chat_ids: list[int],
        default_policy: NotificationPolicy,
        hot_threshold: int,
        token_configured: bool,
        delivery_allowed_by_config: bool,
        worker_active: bool,
        signal_max_age_days: int = 30,
    ) -> None:
        self.session_factory = session_factory
        self.workflow = workflow
        self.manager_chat_ids = list(dict.fromkeys(manager_chat_ids))
        self.default_policy = default_policy
        self.hot_threshold = hot_threshold
        self.token_configured = token_configured
        self.delivery_allowed_by_config = delivery_allowed_by_config
        self.worker_active = worker_active
        self.signal_max_age_days = signal_max_age_days

    async def preview(self, *, limit: int = 10) -> NotificationReadinessReport:
        async with self.session_factory() as session:
            total_uncertain = sum([
                int(await session.scalar(select(func.count(model.id)).where(
                    model.status == NotificationStatus.UNCERTAIN
                )) or 0)
                for model in (NotificationLog, SignificantChangeNotification)
            ])
            rows = (
                await session.execute(
                    select(
                        Lead.id,
                        Lead.assigned_manager_telegram_id,
                        Comment.is_baseline,
                        Comment.created_at_platform,
                        Comment.discovered_at,
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
            targets = (
                [int(row.assigned_manager_telegram_id)]
                if row.assigned_manager_telegram_id else self.manager_chat_ids
            )
            target_count = len(targets)
            decision, reason = self._decision(
                card.status,
                card.score,
                bool(row.is_baseline),
                policy,
                target_count,
                [log for log in logs_by_lead.get(card.lead_id, []) if log.chat_id in targets],
                is_fresh=is_signal_within_window(
                    signal_observed_at(
                        created_at_platform=row.created_at_platform,
                        discovered_at=row.discovered_at,
                    ),
                    max_age_days=self.signal_max_age_days,
                ),
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
            admin_target_count=len(self.manager_chat_ids),
            total_reviewed=len(previews),
            eligible=counts["ELIGIBLE"],
            queued=counts["QUEUED"],
            sent=counts["SENT"],
            suppressed=counts["SUPPRESSED"],
            blocked=counts["BLOCKED"],
            failed=counts["FAILED"],
            uncertain=counts["UNCERTAIN"],
            previews=tuple(previews),
            total_uncertain=total_uncertain,
        )

    def _decision(
        self,
        status: LeadStatus,
        score: int,
        is_baseline: bool,
        policy: NotificationPolicy,
        target_count: int,
        logs: list[NotificationLog],
        *,
        is_fresh: bool = True,
    ) -> tuple[str, str]:
        log_statuses = {log.status for log in logs}
        if NotificationStatus.UNCERTAIN in log_statuses:
            return "UNCERTAIN", "Сетевой результат неоднозначен — требуется ручная сверка."
        if NotificationStatus.SENT in log_statuses:
            return "SENT", "Сообщение уже подтверждено Telegram и повторно не отправится."
        if is_baseline:
            return "SUPPRESSED", "Исторический baseline не создаёт production-уведомление."
        if not is_fresh:
            return "SUPPRESSED", "Сигнал старше окна свежести; остаётся в архиве."
        if target_count == 0:
            return "BLOCKED", "Не назначен менеджер и не настроен получатель уведомлений."
        decision, reason = policy_decision(status, score, policy, self.hot_threshold)
        if decision != "ELIGIBLE":
            return decision, reason
        if NotificationStatus.FAILED in log_statuses:
            return "FAILED", "Предыдущая доставка завершилась подтверждённой ошибкой."
        if log_statuses & {NotificationStatus.PENDING, NotificationStatus.PROCESSING}:
            return "QUEUED", "Карточка ожидает отправки; повторный просмотр не создаёт копию."
        return decision, reason
