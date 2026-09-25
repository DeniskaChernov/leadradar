import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from sqlalchemy import func, select, update

from app.db.models import DailyQualityReportDelivery as Delivery
from app.db.models import DailyQualityReportLog as Report
from app.db.models import NotificationStatus as Status
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.quality_report_delivery_service import QualityReportDeliveryService
from app.services.telegram_notification_service import TelegramLeadNotifier

DAY = date(2026, 9, 24)


class RecordingBot:
    def __init__(self):
        self.calls = []
        self.failures = {}

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append((chat_id, text))
        failure = self.failures.pop(chat_id, None)
        if failure:
            raise failure
        return SimpleNamespace(message_id=len(self.calls))


async def enqueue(service, chat_ids=None, text="persisted report"):
    return await service.enqueue(
        text, report_date=DAY, timezone_name="Asia/Tashkent",
        snapshot={"new_leads": 5}, chat_ids=chat_ids or [1001, 1002],
    )


async def test_report_and_claim_are_committed_before_send_and_workers_cannot_duplicate(file_session_factory):
    factory = file_session_factory

    class InspectingBot(RecordingBot):
        async def send_message(self, chat_id, text, **kwargs):
            # An independent connection must see the content and claim before network I/O.
            async with factory() as session:
                report = await session.scalar(select(Report))
                delivery = await session.scalar(select(Delivery).where(Delivery.chat_id == chat_id))
                assert report.message_text == text
                assert report.snapshot_json == {"new_leads": 5}
                assert delivery.status == Status.PROCESSING
                assert delivery.delivery_started_at is not None
                assert delivery.lease_token
            await asyncio.sleep(0.02)
            return await super().send_message(chat_id, text, **kwargs)

    bot = InspectingBot()
    workers = [QualityReportDeliveryService(bot, factory) for _ in range(2)]
    report_ids = await asyncio.gather(*(enqueue(worker, [1001, 1002, 1001]) for worker in workers))
    assert report_ids[0] == report_ids[1]
    sent = await asyncio.gather(*(worker.flush([1001, 1002]) for worker in workers))
    assert sum(sent) == 2
    assert sorted(bot.calls) == [(1001, "persisted report"), (1002, "persisted report")]
    await enqueue(workers[1], text="replacement must not overwrite")
    assert await workers[1].flush([1001, 1002]) == 0
    async with factory() as session:
        assert await session.scalar(select(func.count(Report.id))) == 1
        assert await session.scalar(select(func.count(Delivery.id))) == 2
        report = await session.scalar(select(Report))
        assert report.sent_at is not None
        assert report.message_text == "persisted report"


async def test_partial_rate_limit_retries_only_rejected_recipient(file_session_factory):
    bot = RecordingBot()
    bot.failures[1002] = TelegramRetryAfter(
        method=SendMessage(chat_id=1002, text="report"), message="wait", retry_after=60
    )
    service = QualityReportDeliveryService(bot, file_session_factory)
    await enqueue(service)
    assert await service.flush([1001, 1002]) == 1
    assert await service.flush([1001, 1002]) == 0
    async with file_session_factory() as session:
        assert (await session.scalar(select(Report))).sent_at is None
        await session.execute(update(Delivery).where(Delivery.chat_id == 1002).values(
            next_attempt_at=datetime.now(UTC) - timedelta(seconds=1)
        ))
        await session.commit()
    # New service instance simulates a restart, outside the original report hour.
    restarted = QualityReportDeliveryService(bot, file_session_factory)
    assert await restarted.flush([1001, 1002]) == 1
    assert [chat for chat, _ in bot.calls] == [1001, 1002, 1002]
    async with file_session_factory() as session:
        assert (await session.scalar(select(Report))).sent_at is not None


async def test_ambiguous_delivery_is_not_automatically_retried(file_session_factory):
    bot = RecordingBot()
    bot.failures[1001] = ConnectionError("secret token must never be stored")
    service = QualityReportDeliveryService(bot, file_session_factory)
    await enqueue(service, [1001])
    assert await service.flush([1001]) == 0
    assert await service.flush([1001]) == 0
    async with file_session_factory() as session:
        row = await session.scalar(select(Delivery))
        assert row.status == Status.UNCERTAIN
        assert row.error == "ConnectionError"
        assert row.attempt_count == 1
    assert len(bot.calls) == 1


async def test_crash_after_committed_claim_becomes_uncertain(file_session_factory):
    bot = RecordingBot()
    bot.failures[1001] = asyncio.CancelledError()
    service = QualityReportDeliveryService(bot, file_session_factory)
    await enqueue(service, [1001])
    with pytest.raises(asyncio.CancelledError):
        await service.flush([1001])
    async with file_session_factory() as session:
        row = await session.scalar(select(Delivery))
        assert row.status == Status.PROCESSING
        stale_token = row.lease_token
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    assert await service.flush([1001]) == 0
    # A late response from an expired worker must not clobber the reconciled state.
    await service._finish(1, stale_token, Status.SENT)
    async with file_session_factory() as session:
        assert (await session.scalar(select(Delivery))).status == Status.UNCERTAIN
    assert len(bot.calls) == 1


async def test_legacy_sent_report_is_never_enqueued_again(file_session_factory):
    async with file_session_factory() as session:
        session.add(Report(
            report_date=DAY, report_timezone="Asia/Tashkent",
            snapshot_json={}, sent_at=datetime.now(UTC),
        ))
        await session.commit()
    bot = RecordingBot()
    service = QualityReportDeliveryService(bot, file_session_factory)
    await enqueue(service)
    assert await service.flush([1001, 1002]) == 0
    assert bot.calls == []
    async with file_session_factory() as session:
        assert await session.scalar(select(func.count(Delivery.id))) == 0


async def test_permanent_rejection_does_not_block_other_recipients(file_session_factory):
    bot = RecordingBot()
    bot.failures[1001] = TelegramForbiddenError(
        method=SendMessage(chat_id=1001, text="report"), message="blocked"
    )
    service = QualityReportDeliveryService(bot, file_session_factory)
    await enqueue(service)
    assert await service.flush([1001, 1002]) == 1
    assert await service.flush([1001, 1002]) == 0
    async with file_session_factory() as session:
        row = await session.scalar(select(Delivery).where(Delivery.chat_id == 1001))
        assert row.status == Status.FAILED


async def test_revoked_recipient_is_not_sent_a_queued_report(file_session_factory):
    bot = RecordingBot()
    service = QualityReportDeliveryService(bot, file_session_factory)
    await enqueue(service)
    assert await service.flush([1002]) == 1
    assert bot.calls == [(1002, "persisted report")]


async def test_disabled_notifier_neither_enqueues_nor_flushes_digests(file_session_factory):
    bot = RecordingBot()
    notifier = TelegramLeadNotifier(
        bot, file_session_factory, LeadWorkflowService(file_session_factory, 70), [],
        hot_threshold=70, admin_chat_ids=[1001], delivery_enabled=False,
    )
    assert await notifier.send_admin_digest(
        "report", report_date=DAY, timezone_name="UTC", snapshot={}
    ) == 0
    assert await notifier.flush_pending() == 0
    async with file_session_factory() as session:
        assert await session.scalar(select(func.count(Report.id))) == 0
    assert bot.calls == []
