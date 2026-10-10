"""Policy rules shared by the delivery queue and its read-only preview."""

from sqlalchemy import and_, func, or_
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Competitor, Lead, LeadStatus, NotificationPolicy

ACTIVE_NOTIFICATION_STATUSES = (LeadStatus.NEW, LeadStatus.TAKEN)


def eligible_policy_clause(
    default_policy: NotificationPolicy, hot_threshold: int,
) -> ColumnElement[bool]:
    policy = func.coalesce(Competitor.notification_policy, default_policy.value)
    return or_(
        policy == NotificationPolicy.ALL_NEW_COMMENTS,
        and_(
            Lead.status.in_(ACTIVE_NOTIFICATION_STATUSES),
            or_(
                policy == NotificationPolicy.COMMERCIAL_ONLY,
                and_(policy == NotificationPolicy.HOT_ONLY, Lead.lead_score >= hot_threshold),
            ),
        ),
    )


def policy_decision(
    status: LeadStatus, score: int, policy: NotificationPolicy, hot_threshold: int,
) -> tuple[str, str]:
    if policy == NotificationPolicy.ALL_NEW_COMMENTS:
        return "ELIGIBLE", "Новый уникальный сигнал подходит под текущую политику."
    if status in {LeadStatus.ANALYZING, LeadStatus.AI_PENDING}:
        return "SUPPRESSED", "Ожидается завершение локальной классификации."
    if status == LeadStatus.NOT_LEAD:
        if policy == NotificationPolicy.HOT_ONLY:
            return "SUPPRESSED", "Статус «Не лид» запрещает HOT-уведомление независимо от балла."
        return "SUPPRESSED", "Сигнал классифицирован как некоммерческий."
    if status not in ACTIVE_NOTIFICATION_STATUSES:
        return "SUPPRESSED", "Контакт уже обработан; новое уведомление о лиде не требуется."
    if policy == NotificationPolicy.COMMERCIAL_ONLY:
        return "ELIGIBLE", "Локальная классификация подтвердила коммерческий интерес."
    if score >= hot_threshold:
        return "ELIGIBLE", f"Лид достиг HOT-порога {hot_threshold}."
    return "SUPPRESSED", f"Лид не достиг HOT-порога {hot_threshold}."
