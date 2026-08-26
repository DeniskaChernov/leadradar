import asyncio
from types import SimpleNamespace

from sqlalchemy import func, select

from app.db.models import NotificationLog, NotificationStatus
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.telegram_notification_service import TelegramLeadNotifier
from tests.test_lead_workflow import create_lead


class RecordingBot:
    def __init__(self) -> None:
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))
        return SimpleNamespace(message_id=len(self.sent))


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
