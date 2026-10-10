from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

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
from app.services.notification_readiness_service import NotificationReadinessService
from app.services.telegram_notification_service import TelegramLeadNotifier
from tests.test_lead_workflow import create_lead
from tests.test_notifications import RecordingBot


def notifier(session_factory, bot=None, workflow=None):
    return TelegramLeadNotifier(
        bot or RecordingBot(), session_factory,
        workflow or LeadWorkflowService(session_factory, 70), [1001],
        hot_threshold=70, notification_policy=NotificationPolicy.HOT_ONLY,
    )


def readiness(session_factory):
    return NotificationReadinessService(
        session_factory, LeadWorkflowService(session_factory, 70),
        manager_chat_ids=[1001], default_policy=NotificationPolicy.HOT_ONLY,
        hot_threshold=70, token_configured=True,
        delivery_allowed_by_config=True, worker_active=True,
    )


@pytest.mark.parametrize("status", [
    LeadStatus.NOT_LEAD, LeadStatus.CONTACTED, LeadStatus.QUALIFIED,
    LeadStatus.OFFER_SENT, LeadStatus.NEGOTIATION, LeadStatus.WON,
    LeadStatus.LOST, LeadStatus.ANALYZING, LeadStatus.AI_PENDING,
])
async def test_hot_queue_rechecks_status_before_delivery(session_factory, status):
    lead_id = await create_lead(session_factory)
    service = notifier(session_factory)
    await service._ensure_log(lead_id, 1001)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.status = status
        await session.commit()

    assert await service.flush_pending() == 0
    assert service.bot.sent == []
    report = await readiness(session_factory).preview()
    assert report.suppressed == 1 and report.queued == 0
    async with session_factory() as session:
        log = await session.scalar(select(NotificationLog))
        assert log.attempt_count == 0 and log.delivery_started_at is None


async def test_lowered_score_waits_until_eligible_without_losing_outbox(session_factory):
    lead_id = await create_lead(session_factory)
    service = notifier(session_factory)
    await service._ensure_log(lead_id, 1001)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.lead_score = 69
        await session.commit()
    assert await service.flush_pending() == 0
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.lead_score = 82
        await session.commit()
    assert await service.flush_pending() == 1
    assert await service.flush_pending() == 0
    assert len(service.bot.sent) == 1


async def test_reassigned_lead_skips_old_recipient_queue(session_factory):
    lead_id = await create_lead(session_factory)
    service = notifier(session_factory)
    await service._ensure_log(lead_id, 1001)
    await service.workflow.assign_manager(lead_id, 2002)

    assert await service.flush_pending() == 1
    assert [row[0] for row in service.bot.sent] == [2002]
    assert await service.flush_pending() == 0
    report = await readiness(session_factory).preview()
    assert report.sent == 1 and report.queued == 0
    async with session_factory() as session:
        old = await session.scalar(select(NotificationLog).where(NotificationLog.chat_id == 1001))
        assert old.attempt_count == 0 and old.delivery_started_at is None


async def test_changed_source_policy_blocks_unqualified_queued_comment(session_factory):
    lead_id = await create_lead(session_factory)
    service = notifier(session_factory)
    await service._ensure_log(lead_id, 1001)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.status = LeadStatus.ANALYZING
        lead.lead_score = 0
        source = await session.get(Competitor, lead.competitor_id)
        source.notification_policy = NotificationPolicy.HOT_ONLY
        await session.commit()
    assert await service.flush_pending() == 0
    assert service.bot.sent == []


@pytest.mark.parametrize("baseline", [False, True])
async def test_direct_delivery_claim_cannot_bypass_freshness(session_factory, baseline):
    lead_id = await create_lead(session_factory)
    service = notifier(session_factory)
    await service._ensure_log(lead_id, 1001)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        comment = await session.get(Comment, lead.comment_id)
        if baseline:
            comment.is_baseline = True
        else:
            comment.created_at_platform = datetime.now(UTC) - timedelta(days=31)
        log_id = await session.scalar(select(NotificationLog.id))
        await session.commit()
    assert await service._claim_and_send(log_id) is False
    assert service.bot.sent == []


async def test_local_card_failure_is_retryable_without_ambiguous_delivery(session_factory, monkeypatch):
    lead_id = await create_lead(session_factory)
    service = notifier(session_factory)
    await service._ensure_log(lead_id, 1001)
    original = service.workflow.get_lead_card

    async def broken_card(_lead_id):
        raise ValueError("Local card assembly failed")

    monkeypatch.setattr(service.workflow, "get_lead_card", broken_card)
    assert await service._deliver_pending() == 0
    async with session_factory() as session:
        log = await session.scalar(select(NotificationLog))
        assert log.status == NotificationStatus.FAILED
        assert log.delivery_started_at is None and log.uncertain_at is None
        log.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    assert service.bot.sent == []
    monkeypatch.setattr(service.workflow, "get_lead_card", original)
    assert await service.flush_pending() == 1
    assert len(service.bot.sent) == 1


async def test_manager_rejection_during_card_assembly_prevents_send(session_factory, monkeypatch):
    lead_id = await create_lead(session_factory)
    service = notifier(session_factory)
    await service._ensure_log(lead_id, 1001)
    original = service.workflow.get_lead_card

    async def card_then_rejection(requested):
        card = await original(requested)
        await service.workflow.mark_not_lead(requested, 1001)
        return card

    monkeypatch.setattr(service.workflow, "get_lead_card", card_then_rejection)
    assert await service._deliver_pending() == 0
    assert service.bot.sent == []
    async with session_factory() as session:
        log = await session.scalar(select(NotificationLog))
        assert log.status == NotificationStatus.PENDING
        assert log.attempt_count == 0 and log.lease_token is None
        assert log.delivery_started_at is None


async def test_readiness_sees_uncertain_delivery_outside_preview_window(session_factory):
    old = await create_lead(session_factory, "old-uncertain")
    async with session_factory() as session:
        session.add(NotificationLog(
            lead_id=old, chat_id=1001, idempotency_key=f"lead:{old}:chat:1001",
            status=NotificationStatus.UNCERTAIN,
        ))
        await session.commit()
    for i in range(10):
        await create_lead(session_factory, f"new-{i}", f"user-{i}")
    report = await readiness(session_factory).preview(limit=10)
    assert report.uncertain == 0
    assert report.controlled_pilot_ready is False
    assert report.total_uncertain == 1
    assert report.delivery_active is True


@pytest.mark.parametrize("policy,status,score,expected", [
    (NotificationPolicy.ALL_NEW_COMMENTS, LeadStatus.ANALYZING, 0, 1),
    (NotificationPolicy.ALL_NEW_COMMENTS, LeadStatus.NOT_LEAD, 0, 1),
    (NotificationPolicy.COMMERCIAL_ONLY, LeadStatus.NEW, 50, 1),
    (NotificationPolicy.COMMERCIAL_ONLY, LeadStatus.CONTACTED, 82, 0),
    (NotificationPolicy.HOT_ONLY, LeadStatus.NEW, 69, 0),
    (NotificationPolicy.HOT_ONLY, LeadStatus.TAKEN, 82, 1),
])
async def test_source_policy_delivery_matches_preview(session_factory, policy, status, score, expected):
    lead_id = await create_lead(session_factory)
    service = notifier(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.status, lead.lead_score = status, score
        source = await session.get(Competitor, lead.competitor_id)
        source.notification_policy = policy
        await session.commit()
    report = await readiness(session_factory).preview()
    assert report.eligible == expected
    await service._ensure_log(lead_id, 1001)
    assert await service._deliver_pending() == expected
    assert len(service.bot.sent) == expected


async def test_local_change_render_failure_is_not_an_ambiguous_send(session_factory, monkeypatch):
    from app.db.models import SignificantChangeNotification
    from app.services import telegram_notification_service as delivery_module
    from app.services.contact_service import ContactService
    from tests.test_contact_service import make_comment, make_post
    from tests.test_significant_changes import _service

    contacts = ContactService(session_factory)
    analysis = _service(session_factory)
    first = await contacts.persist_signal(make_post(), make_comment("local-change-first"))
    await analysis.process_signal(first)
    changed_post = make_post().model_copy(update={
        "platform_post_id": "local-change-post", "competitor": "dafna.uz",
        "url": "https://www.instagram.com/reel/local-change-post/",
    })
    second = await contacts.persist_signal(changed_post, make_comment("local-change-second"))
    result = await analysis.process_signal(second)
    assert result.significant_change_id is not None
    service = notifier(session_factory)
    original = delivery_module.render_significant_change

    def invalid_card(*_args):
        raise ValueError("Local formatting error")

    monkeypatch.setattr(delivery_module, "render_significant_change", invalid_card)
    assert await service.notify_significant_change(result.significant_change_id) == 0
    assert service.bot.sent == []
    async with session_factory() as session:
        log = await session.scalar(select(SignificantChangeNotification))
        assert log.status == NotificationStatus.FAILED and log.uncertain_at is None
        assert log.delivery_started_at is None
        log.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    monkeypatch.setattr(delivery_module, "render_significant_change", original)
    assert await service._deliver_pending_changes(change_id=result.significant_change_id) == 1
    assert len(service.bot.sent) == 1
