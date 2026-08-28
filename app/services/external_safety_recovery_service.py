from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AIRequest,
    AIRequestStatus,
    ExternalBudgetReservation,
    ReservationStatus,
)
from app.services.usage_service import ExternalUsageService


@dataclass(frozen=True, slots=True)
class RecoveryStats:
    ai_retryable: int = 0
    ai_permanent: int = 0
    reservations_released: int = 0
    reservations_counted_uncertain: int = 0


class ExternalSafetyRecoveryService:
    """Idempotently reconcile stale leases without understating possible spend."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        usage: ExternalUsageService,
        *,
        max_ai_attempts: int,
    ) -> None:
        self.session_factory = session_factory
        self.usage = usage
        self.max_ai_attempts = max_ai_attempts

    async def recover(self) -> RecoveryStats:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            stale_ai = (
                await session.scalars(
                    select(AIRequest).where(
                        AIRequest.status == AIRequestStatus.CLAIMED,
                        AIRequest.claim_expires_at <= now,
                    )
                )
            ).all()
            stale_reservations = (
                await session.scalars(
                    select(ExternalBudgetReservation).where(
                        ExternalBudgetReservation.status == ReservationStatus.RESERVED,
                        ExternalBudgetReservation.expires_at <= now,
                    )
                )
            ).all()

            retryable = sum(item.attempt_count < self.max_ai_attempts for item in stale_ai)
            permanent = len(stale_ai) - retryable
            for item in stale_ai:
                final = (
                    AIRequestStatus.RETRYABLE
                    if item.attempt_count < self.max_ai_attempts
                    else AIRequestStatus.PERMANENT_FAILURE
                )
                await session.execute(
                    update(AIRequest)
                    .where(
                        AIRequest.id == item.id,
                        AIRequest.status == AIRequestStatus.CLAIMED,
                    )
                    .values(
                        status=final,
                        claim_token=None,
                        claim_expires_at=None,
                        worker_id=None,
                        error="Recovered stale AI claim",
                        error_type="STALE_CLAIM",
                        error_message="Recovered stale AI claim after worker interruption",
                        completed_at=(now if final == AIRequestStatus.PERMANENT_FAILURE else None),
                    )
                )
            await session.commit()

        released = 0
        uncertain = 0
        for reservation in stale_reservations:
            if reservation.call_started_at is None:
                await self.usage.release_reservation(reservation.id)
                released += 1
            else:
                request_succeeded = await self._request_succeeded(reservation.reservation_key)
                await self.usage.finalize_reservation(
                    reservation.id,
                    units=reservation.units_reserved,
                    success=request_succeeded,
                    details={
                        "billing_state": (
                            "SUCCEEDED_RECOVERED_AFTER_LEDGER_GAP"
                            if request_succeeded
                            else "UNKNOWN_RECOVERED_AFTER_STALE_LEASE"
                        )
                    },
                )
                uncertain += 1
        return RecoveryStats(retryable, permanent, released, uncertain)

    async def _request_succeeded(self, reservation_key: str) -> bool:
        parts = reservation_key.split(":", 2)
        if len(parts) < 2 or parts[0] != "ai" or not parts[1].isdigit():
            return False
        async with self.session_factory() as session:
            status = await session.scalar(
                select(AIRequest.status).where(AIRequest.id == int(parts[1]))
            )
        return status == AIRequestStatus.SUCCEEDED
