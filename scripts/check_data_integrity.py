from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import (
    AudienceMembership,
    AudienceSegment,
    BusinessAlias,
    BusinessEntity,
    Comment,
    Contact,
    ContactEvent,
    ContactIntelligence,
    Deal,
    Evidence,
    Lead,
    NotificationLog,
    Post,
    PublicSignal,
    SignificantChange,
    SignificantChangeNotification,
)
from app.db.session import create_engine, create_session_factory


@dataclass(frozen=True, slots=True)
class IntegrityResult:
    counts: dict[str, int]
    duplicates: dict[str, int]

    @property
    def valid(self) -> bool:
        return not any(self.duplicates.values())


async def inspect_integrity() -> IntegrityResult:
    engine = create_engine(get_settings())
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            models = (
                Contact,
                BusinessEntity,
                BusinessAlias,
                ContactIntelligence,
                AudienceSegment,
                AudienceMembership,
                Post,
                Comment,
                PublicSignal,
                Lead,
                Deal,
                ContactEvent,
                NotificationLog,
                SignificantChange,
                SignificantChangeNotification,
                Evidence,
            )
            counts = {
                model.__tablename__: await session.scalar(select(func.count(model.id))) or 0
                for model in models
            }
            checks = {
                "comment IDs": select(
                    Comment.platform, Comment.platform_comment_id, func.count()
                )
                .group_by(Comment.platform, Comment.platform_comment_id)
                .having(func.count() > 1),
                "post URLs": select(Post.platform, Post.url, func.count())
                .group_by(Post.platform, Post.url)
                .having(func.count() > 1),
                "lead comments": select(Lead.comment_id, func.count())
                .group_by(Lead.comment_id)
                .having(func.count() > 1),
                "public signal comments": select(PublicSignal.comment_id, func.count())
                .group_by(PublicSignal.comment_id)
                .having(func.count() > 1),
                "public signal dedupe keys": select(
                    PublicSignal.dedupe_key, func.count()
                )
                .group_by(PublicSignal.dedupe_key)
                .having(func.count() > 1),
                "public signal external identities": select(
                    PublicSignal.platform,
                    PublicSignal.signal_type,
                    PublicSignal.external_id,
                    func.count(),
                )
                .where(PublicSignal.external_id.is_not(None))
                .group_by(
                    PublicSignal.platform,
                    PublicSignal.signal_type,
                    PublicSignal.external_id,
                )
                .having(func.count() > 1),
                "business canonical keys": select(
                    BusinessEntity.canonical_key, func.count()
                )
                .group_by(BusinessEntity.canonical_key)
                .having(func.count() > 1),
                "business aliases": select(
                    BusinessAlias.business_id,
                    BusinessAlias.alias_type,
                    BusinessAlias.normalized_value,
                    func.count(),
                )
                .group_by(
                    BusinessAlias.business_id,
                    BusinessAlias.alias_type,
                    BusinessAlias.normalized_value,
                )
                .having(func.count() > 1),
                "evidence keys": select(Evidence.evidence_key, func.count())
                .group_by(Evidence.evidence_key)
                .having(func.count() > 1),
                "contact intelligence profiles": select(
                    ContactIntelligence.contact_id, func.count()
                )
                .group_by(ContactIntelligence.contact_id)
                .having(func.count() > 1),
                "audience memberships": select(
                    AudienceMembership.segment_id,
                    AudienceMembership.contact_id,
                    func.count(),
                )
                .group_by(
                    AudienceMembership.segment_id, AudienceMembership.contact_id
                )
                .having(func.count() > 1),
                "deal leads": select(Deal.lead_id, func.count())
                .where(Deal.lead_id.is_not(None))
                .group_by(Deal.lead_id)
                .having(func.count() > 1),
                "notification targets": select(
                    NotificationLog.lead_id, NotificationLog.chat_id, func.count()
                )
                .group_by(NotificationLog.lead_id, NotificationLog.chat_id)
                .having(func.count() > 1),
                "notification idempotency keys": select(
                    NotificationLog.idempotency_key, func.count()
                )
                .group_by(NotificationLog.idempotency_key)
                .having(func.count() > 1),
                "significant changes per lead": select(
                    SignificantChange.lead_id, func.count()
                )
                .group_by(SignificantChange.lead_id)
                .having(func.count() > 1),
                "significant change notification targets": select(
                    SignificantChangeNotification.change_id,
                    SignificantChangeNotification.chat_id,
                    func.count(),
                )
                .group_by(
                    SignificantChangeNotification.change_id,
                    SignificantChangeNotification.chat_id,
                )
                .having(func.count() > 1),
                "significant change notification idempotency keys": select(
                    SignificantChangeNotification.idempotency_key, func.count()
                )
                .group_by(SignificantChangeNotification.idempotency_key)
                .having(func.count() > 1),
            }
            duplicates = {
                name: len((await session.execute(query)).all())
                for name, query in checks.items()
            }
            return IntegrityResult(counts=counts, duplicates=duplicates)
    finally:
        await engine.dispose()


def main() -> None:
    result = asyncio.run(inspect_integrity())
    print("Lead Radar data integrity")
    print("=" * 32)
    for name, count in result.counts.items():
        print(f"{name:<22} {count}")
    print("-" * 32)
    for name, count in result.duplicates.items():
        status = "OK" if count == 0 else "FAIL"
        print(f"[{status:<4}] duplicate {name}: {count}")
    print("=" * 32)
    print("Result: OK" if result.valid else "Result: duplicate data found")
    raise SystemExit(0 if result.valid else 1)


if __name__ == "__main__":
    main()
