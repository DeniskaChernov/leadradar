import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import func, select

from app.db.models import Lead, LeadStatus, NotificationLog, NotificationStatus
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.telegram_notification_service import TelegramLeadNotifier
from tests.test_lead_workflow import create_lead


class RecordingBot:
    def __init__(self) -> None:
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))
        return SimpleNamespace(message_id=len(self.sent))


class EditFailingBot(RecordingBot):
    def __init__(self) -> None:
        super().__init__()
        self.edit_attempts = 0

    async def edit_message_text(self, **kwargs):
        self.edit_attempts += 1
        raise RuntimeError("message cannot be edited")


class AmbiguousBot(RecordingBot):
    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))
        raise ConnectionError("connection lost after request write")


class EditingBot(RecordingBot):
    def __init__(self) -> None:
        super().__init__()
        self.edits = []

    async def edit_message_text(self, **kwargs):
        await asyncio.sleep(0.05)
        self.edits.append(kwargs)


async def test_notification_outbox_prevents_duplicate_delivery(session_factory):
    lead_id = await create_lead(session_factory)
    bot = RecordingBot()
    notifier = TelegramLeadNotifier(
        bot,
        session_factory,
        LeadWorkflowService(session_factory, 70),
        [1001],
        hot_threshold=70,
        max_attempts=3,
    )

    results = await asyncio.gather(
        notifier.notify_hot_lead(lead_id),
        notifier.notify_hot_lead(lead_id),
    )
    await notifier.flush_pending()

    assert sum(results) == 1
    assert len(bot.sent) == 1
    async with session_factory() as session:
        assert await session.scalar(select(func.count(NotificationLog.id))) == 1
        log = await session.scalar(select(NotificationLog))
        assert log is not None
        assert log.status == NotificationStatus.SENT
        assert log.attempt_count == 1


async def test_notification_is_routed_to_assigned_manager(session_factory):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.assigned_manager_telegram_id = 2002
        await session.commit()
    bot = RecordingBot()
    notifier = TelegramLeadNotifier(
        bot,
        session_factory,
        LeadWorkflowService(session_factory, 70),
        [1001],
        hot_threshold=70,
    )

    assert await notifier.notify_hot_lead(lead_id) == 1
    assert bot.sent[0][0] == 2002


async def test_enrichment_edit_failure_sends_one_safe_followup(session_factory):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.status = LeadStatus.ANALYZING
        lead.lead_score = 0
        await session.commit()
    bot = EditFailingBot()
    notifier = TelegramLeadNotifier(
        bot,
        session_factory,
        LeadWorkflowService(session_factory, 70),
        [1001],
        hot_threshold=70,
    )

    assert await notifier.notify_new_signal(lead_id) == 1
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.status = LeadStatus.NEW
        lead.lead_score = 91
        await session.commit()

    await notifier.notify_analyzed_lead(lead_id)
    await notifier.notify_analyzed_lead(lead_id)

    assert bot.edit_attempts == 1
    assert len(bot.sent) == 2
    assert "Новый сигнал" in bot.sent[0][1]
    assert "Анализ сигнала завершён" in bot.sent[1][1]
    async with session_factory() as session:
        log = await session.scalar(select(NotificationLog))
        assert log is not None
        assert log.content_version == 2
        assert log.enrichment_followup_sent_at is not None


async def test_replay_delivery_guard_never_sends_production_notification(session_factory):
    lead_id = await create_lead(session_factory)
    bot = RecordingBot()
    notifier = TelegramLeadNotifier(
        bot,
        session_factory,
        LeadWorkflowService(session_factory, 70),
        [1001],
        hot_threshold=70,
        delivery_enabled=False,
    )

    assert await notifier.notify_new_signal(lead_id) == 0
    assert await notifier.notify_hot_lead(lead_id) == 0
    assert await notifier.flush_pending() == 0
    assert bot.sent == []


async def test_two_notifier_instances_share_one_atomic_delivery_claim(session_factory):
    lead_id = await create_lead(session_factory)
    bot = RecordingBot()
    first = TelegramLeadNotifier(
        bot,
        session_factory,
        LeadWorkflowService(session_factory, 70),
        [1001],
        hot_threshold=70,
        worker_id="worker-a",
    )
    second = TelegramLeadNotifier(
        bot,
        session_factory,
        LeadWorkflowService(session_factory, 70),
        [1001],
        hot_threshold=70,
        worker_id="worker-b",
    )
    await first._ensure_log(lead_id, 1001)

    results = await asyncio.gather(
        first._deliver_pending(lead_id=lead_id),
        second._deliver_pending(lead_id=lead_id),
    )

    assert sum(results) == 1
    assert len(bot.sent) == 1
    async with session_factory() as session:
        log = await session.scalar(select(NotificationLog))
        assert log is not None
        assert log.status == NotificationStatus.SENT
        assert log.idempotency_key == f"lead:{lead_id}:chat:1001"
        assert log.lease_token is None


async def test_expired_pre_delivery_claim_is_safely_requeued(session_factory):
    lead_id = await create_lead(session_factory)
    bot = RecordingBot()
    notifier = TelegramLeadNotifier(
        bot,
        session_factory,
        LeadWorkflowService(session_factory, 70),
        [1001],
        hot_threshold=70,
    )
    await notifier._ensure_log(lead_id, 1001)
    async with session_factory() as session:
        log = await session.scalar(select(NotificationLog))
        assert log is not None
        log.status = NotificationStatus.PROCESSING
        log.attempt_count = 1
        log.lease_owner = "dead-worker"
        log.lease_token = "expired"
        log.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    assert await notifier.flush_pending() == 1
    assert len(bot.sent) == 1
    async with session_factory() as session:
        log = await session.scalar(select(NotificationLog))
        assert log is not None
        assert log.status == NotificationStatus.SENT
        assert log.attempt_count == 2


async def test_expired_started_delivery_becomes_uncertain_without_resend(session_factory):
    lead_id = await create_lead(session_factory)
    bot = RecordingBot()
    notifier = TelegramLeadNotifier(
        bot,
        session_factory,
        LeadWorkflowService(session_factory, 70),
        [1001],
        hot_threshold=70,
    )
    await notifier._ensure_log(lead_id, 1001)
    async with session_factory() as session:
        log = await session.scalar(select(NotificationLog))
        assert log is not None
        log.status = NotificationStatus.PROCESSING
        log.attempt_count = 1
        log.lease_owner = "dead-worker"
        log.lease_token = "expired-after-send"
        log.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        log.delivery_started_at = datetime.now(UTC) - timedelta(seconds=2)
        await session.commit()

    assert await notifier.flush_pending() == 0
    assert await notifier.flush_pending() == 0
    assert bot.sent == []
    async with session_factory() as session:
        log = await session.scalar(select(NotificationLog))
        assert log is not None
        assert log.status == NotificationStatus.UNCERTAIN
        assert log.uncertain_at is not None


async def test_ambiguous_network_failure_is_never_automatically_retried(session_factory):
    lead_id = await create_lead(session_factory)
    bot = AmbiguousBot()
    notifier = TelegramLeadNotifier(
        bot,
        session_factory,
        LeadWorkflowService(session_factory, 70),
        [1001],
        hot_threshold=70,
    )

    assert await notifier.notify_hot_lead(lead_id) == 0
    assert await notifier.flush_pending() == 0
    assert len(bot.sent) == 1
    async with session_factory() as session:
        log = await session.scalar(select(NotificationLog))
        assert log is not None
        assert log.status == NotificationStatus.UNCERTAIN
        assert log.next_attempt_at is None


async def test_uncertain_delivery_requires_explicit_resolution_before_requeue(
    session_factory,
):
    lead_id = await create_lead(session_factory)
    ambiguous_bot = AmbiguousBot()
    notifier = TelegramLeadNotifier(
        ambiguous_bot,
        session_factory,
        LeadWorkflowService(session_factory, 70),
        [1001],
        hot_threshold=70,
    )
    assert await notifier.notify_hot_lead(lead_id) == 0
    async with session_factory() as session:
        log = await session.scalar(select(NotificationLog))
        assert log is not None
        log_id = log.id

    assert await notifier.resolve_uncertain_lead_delivery(
        log_id, delivered=False
    )
    working_bot = RecordingBot()
    recovery = TelegramLeadNotifier(
        working_bot,
        session_factory,
        LeadWorkflowService(session_factory, 70),
        [1001],
        hot_threshold=70,
    )
    assert await recovery.flush_pending() == 1
    assert len(working_bot.sent) == 1
    async with session_factory() as session:
        log = await session.get(NotificationLog, log_id)
        assert log is not None
        assert log.status == NotificationStatus.SENT
        assert log.resolution == "CONFIRMED_NOT_SENT_REQUEUED"


async def test_message_edit_has_one_claim_across_notifier_instances(session_factory):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.status = LeadStatus.ANALYZING
        lead.lead_score = 0
        await session.commit()
    bot = EditingBot()
    first = TelegramLeadNotifier(
        bot,
        session_factory,
        LeadWorkflowService(session_factory, 70),
        [1001],
        hot_threshold=70,
        worker_id="edit-a",
    )
    second = TelegramLeadNotifier(
        bot,
        session_factory,
        LeadWorkflowService(session_factory, 70),
        [1001],
        hot_threshold=70,
        worker_id="edit-b",
    )
    assert await first.notify_new_signal(lead_id) == 1
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.status = LeadStatus.NEW
        lead.lead_score = 90
        await session.commit()

    await asyncio.gather(
        first.notify_analyzed_lead(lead_id), second.notify_analyzed_lead(lead_id)
    )

    assert len(bot.edits) == 1
    async with session_factory() as session:
        log = await session.scalar(select(NotificationLog))
        assert log is not None
        assert log.content_version == 2
        assert log.edit_attempt_count == 1
