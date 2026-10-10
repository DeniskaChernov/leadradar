from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.config import Settings
from app.db.models import Comment, Lead, NotificationLog, NotificationPolicy
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.notification_readiness_service import NotificationReadinessService
from app.services.telegram_notification_service import TelegramLeadNotifier
from tests.test_lead_workflow import create_lead
from tests.test_notifications import RecordingBot


def test_admin_can_receive_leads_without_becoming_a_manager():
    settings = Settings(_env_file=None, telegram_admin_chat_ids=[1001],
                        telegram_notification_chat_ids="1001,1001")
    assert settings.telegram_lead_delivery_chat_ids == [1001]
    assert settings.telegram_manager_chat_ids == []
    assert settings.telegram_admin_chat_ids == [1001]


def test_notification_targets_preserve_legacy_manager_default():
    settings = Settings(_env_file=None, telegram_manager_chat_ids=[2002, 2002])
    assert settings.telegram_lead_delivery_chat_ids == [2002]


@pytest.mark.parametrize("roles", [{}, {"telegram_viewer_chat_ids": [3003]}])
def test_notification_recipient_must_have_admin_or_manager_access(roles):
    with pytest.raises(ValidationError, match="notification recipients"):
        Settings(_env_file=None, telegram_notification_chat_ids=[3003], **roles)


@pytest.mark.parametrize("mode", ["web-only", "full"])
def test_persisted_windows_runtime_mode(mode):
    settings = Settings(_env_file=None, windows_runtime_mode=mode)
    assert settings.windows_runtime_mode == mode


def test_unknown_windows_runtime_mode_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, windows_runtime_mode="once")


async def test_hot_backlog_delivery_filters_archive_and_baseline_and_is_idempotent(session_factory):
    fresh = await create_lead(session_factory, "notify-fresh", "fresh")
    archive = await create_lead(session_factory, "notify-archive", "archive")
    baseline = await create_lead(session_factory, "notify-baseline", "baseline")
    async with session_factory() as session:
        for lid in (archive, baseline):
            lead = await session.get(Lead, lid)
            comment = await session.get(Comment, lead.comment_id)
            if lid == archive:
                comment.created_at_platform = datetime.now(UTC) - timedelta(days=31)
            else:
                comment.is_baseline = True
        await session.commit()
    bot = RecordingBot()
    notifier = TelegramLeadNotifier(
        bot, session_factory, LeadWorkflowService(session_factory, 70), [1001],
        hot_threshold=70, notification_policy=NotificationPolicy.HOT_ONLY,
        signal_max_age_days=30)
    assert await notifier.notify_hot_lead(archive) == 0
    assert await notifier.notify_hot_lead(baseline) == 0
    assert await notifier.flush_pending() == 1
    assert await notifier.flush_pending() == 0
    assert await notifier.notify_analyzed_lead(fresh) == 0
    assert len(bot.sent) == 1 and bot.sent[0][0] == 1001
    async with session_factory() as session:
        assert await session.scalar(select(func.count(NotificationLog.id))) == 1
        assert await session.scalar(select(NotificationLog.lead_id)) == fresh


async def test_archived_pending_outbox_is_not_delivered(session_factory):
    lead_id = await create_lead(session_factory, "queued-archive")
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        comment = await session.get(Comment, lead.comment_id)
        comment.created_at_platform = datetime.now(UTC) - timedelta(days=31)
        session.add(NotificationLog(lead_id=lead_id, chat_id=1001,
                                    idempotency_key=f"lead:{lead_id}:chat:1001"))
        await session.commit()
    bot = RecordingBot()
    notifier = TelegramLeadNotifier(
        bot, session_factory, LeadWorkflowService(session_factory, 70), [1001],
        hot_threshold=70, signal_max_age_days=30)
    assert await notifier.flush_pending() == 0 and not bot.sent


async def test_notification_preview_matches_archived_delivery_suppression(session_factory):
    lead_id = await create_lead(session_factory, "preview-archive")
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        comment = await session.get(Comment, lead.comment_id)
        comment.created_at_platform = datetime.now(UTC) - timedelta(days=31)
        await session.commit()
    preview = await NotificationReadinessService(
        session_factory, LeadWorkflowService(session_factory, 70), manager_chat_ids=[1001],
        default_policy=NotificationPolicy.HOT_ONLY, hot_threshold=70,
        token_configured=True, delivery_allowed_by_config=True, worker_active=True,
        signal_max_age_days=30).preview()
    assert preview.suppressed == 1 and preview.eligible == 0
    assert "окна свежести" in preview.previews[0].reason
