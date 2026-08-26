from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import (
    Comment,
    Contact,
    ContactEvent,
    Deal,
    Lead,
    NotificationLog,
    Post,
    PublicSignal,
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
                Post,
                Comment,
                PublicSignal,
                Lead,
                Deal,
                ContactEvent,
                NotificationLog,
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
                "deal leads": select(Deal.lead_id, func.count())
                .where(Deal.lead_id.is_not(None))
                .group_by(Deal.lead_id)
                .having(func.count() > 1),
                "notification targets": select(
                    NotificationLog.lead_id, NotificationLog.chat_id, func.count()
                )
                .group_by(NotificationLog.lead_id, NotificationLog.chat_id)
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
