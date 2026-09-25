"""Transactional per-recipient outbox for daily Telegram quality reports."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
)
from sqlalchemy import exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import DailyQualityReportDelivery as Delivery
from app.db.models import DailyQualityReportLog as Report
from app.db.models import NotificationStatus as Status


class QualityReportDeliveryService:
    def __init__(
        self,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        lease_seconds: int = 120,
        max_attempts: int = 3,
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    async def enqueue(
        self,
        text: str,
        *,
        report_date: date,
        timezone_name: str,
        snapshot: dict,
        chat_ids: list[int],
    ) -> int:
        """Persist immutable content and all recipients in one commit; legacy reports stay sent."""
        targets = sorted(set(chat_ids))
        if not targets:
            raise ValueError("A quality report needs at least one recipient")
        async with self.session_factory() as session:
            existing = await session.scalar(select(Report.id).where(
                Report.report_date == report_date, Report.report_timezone == timezone_name
            ))
            if existing is not None:
                return existing
            report = Report(
                report_date=report_date, report_timezone=timezone_name,
                message_text=text, snapshot_json=snapshot, sent_at=None,
            )
            session.add(report)
            try:
                await session.flush()
                session.add_all([Delivery(report_id=report.id, chat_id=chat_id) for chat_id in targets])
                await session.commit()
                return report.id
            except IntegrityError:
                await session.rollback()
                # A competing worker may have committed this day/timezone first.
                existing = await session.scalar(select(Report.id).where(
                    Report.report_date == report_date, Report.report_timezone == timezone_name
                ))
                if existing is None:
                    raise
                return existing

    async def flush(self, allowed_chat_ids: list[int]) -> int:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            # A network call could have succeeded before a crash. Never auto-resend it.
            await session.execute(update(Delivery).where(
                Delivery.status == Status.PROCESSING,
                Delivery.lease_expires_at <= now,
            ).values(status=Status.UNCERTAIN, error="delivery_lease_expired"))
            await session.commit()
            ids = list(await session.scalars(select(Delivery.id).where(
                Delivery.status == Status.PENDING,
                Delivery.chat_id.in_(allowed_chat_ids),
                Delivery.attempt_count < self.max_attempts,
                or_(Delivery.next_attempt_at.is_(None), Delivery.next_attempt_at <= now),
            ).order_by(Delivery.id).limit(100)))
        sent = 0
        for delivery_id in ids:
            sent += await self._deliver(delivery_id, allowed_chat_ids)
        # Separate transaction after recipient commits also handles concurrent final sends
        # and a restart after delivery succeeded but the report timestamp was not written.
        async with self.session_factory() as session:
            await session.execute(update(Report).where(
                Report.sent_at.is_(None),
                exists().where(Delivery.report_id == Report.id),
                ~exists().where(Delivery.report_id == Report.id, Delivery.status != Status.SENT),
            ).values(sent_at=datetime.now(UTC)))
            await session.commit()
        return sent

    async def _deliver(self, delivery_id: int, allowed_chat_ids: list[int]) -> int:
        token = uuid4().hex
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            claim = (await session.execute(update(Delivery).where(
                Delivery.id == delivery_id,
                Delivery.status == Status.PENDING,
                Delivery.chat_id.in_(allowed_chat_ids),
                Delivery.attempt_count < self.max_attempts,
                or_(Delivery.next_attempt_at.is_(None), Delivery.next_attempt_at <= now),
            ).values(
                status=Status.PROCESSING,
                attempt_count=Delivery.attempt_count + 1,
                lease_token=token,
                lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                delivery_started_at=now,
                next_attempt_at=None,
            ).returning(Delivery.report_id, Delivery.chat_id, Delivery.attempt_count))).one_or_none()
            await session.commit()
            if claim is None:
                return 0
            message_text = await session.scalar(select(Report.message_text).where(Report.id == claim.report_id))
        if not message_text:
            await self._finish(delivery_id, token, Status.FAILED, error="missing_persisted_message")
            return 0
        try:
            message = await self.bot.send_message(
                claim.chat_id, message_text, disable_web_page_preview=True
            )
        except TelegramRetryAfter as exc:
            retry = claim.attempt_count < self.max_attempts
            await self._finish(
                delivery_id, token, Status.PENDING if retry else Status.FAILED,
                error=type(exc).__name__,
                next_attempt_at=datetime.now(UTC) + timedelta(seconds=max(1, exc.retry_after)) if retry else None,
            )
            return 0
        except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound, TelegramUnauthorizedError) as exc:
            await self._finish(delivery_id, token, Status.FAILED, error=type(exc).__name__)
            return 0
        except Exception as exc:
            # Do not store exception strings: they can contain tokens or message content.
            await self._finish(delivery_id, token, Status.UNCERTAIN, error=type(exc).__name__)
            return 0
        await self._finish(
            delivery_id, token, Status.SENT,
            message_id=message.message_id, sent_at=datetime.now(UTC), error=None,
        )
        return 1

    async def _finish(self, delivery_id: int, token: str, status: Status, **values) -> None:
        async with self.session_factory() as session:
            await session.execute(update(Delivery).where(
                Delivery.id == delivery_id, Delivery.lease_token == token,
                Delivery.status == Status.PROCESSING,
            ).values(status=status, lease_token=None, lease_expires_at=None, **values))
            await session.commit()
