from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import NotificationLog, NotificationPolicy
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.notification_readiness_service import NotificationReadinessService
from tests.test_lead_workflow import create_lead


async def test_notification_preview_is_read_only_and_repeatable(session_factory):
    lead_id = await create_lead(session_factory, "notification-preview")
    service = NotificationReadinessService(
        session_factory,
        LeadWorkflowService(session_factory, 70),
        manager_chat_ids=[1001, 1001],
        default_policy=NotificationPolicy.ALL_NEW_COMMENTS,
        hot_threshold=70,
        token_configured=True,
        delivery_allowed_by_config=True,
        worker_active=False,
    )

    first = await service.preview()
    second = await service.preview()
    async with session_factory() as session:
        log_count = int(await session.scalar(select(func.count(NotificationLog.id))) or 0)

    assert first == second
    assert first.previews[0].lead_id == lead_id
    assert first.previews[0].decision == "ELIGIBLE"
    assert first.previews[0].target_count == 1
    assert first.controlled_pilot_ready is False
    assert log_count == 0


async def test_notification_preview_blocks_missing_manager_target(session_factory):
    await create_lead(session_factory, "notification-no-target")
    service = NotificationReadinessService(
        session_factory,
        LeadWorkflowService(session_factory, 70),
        manager_chat_ids=[],
        default_policy=NotificationPolicy.ALL_NEW_COMMENTS,
        hot_threshold=70,
        token_configured=True,
        delivery_allowed_by_config=True,
        worker_active=True,
    )

    report = await service.preview()

    assert report.blocked == 1
    assert report.previews[0].decision == "BLOCKED"
    assert report.controlled_pilot_ready is False
