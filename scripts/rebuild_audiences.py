from __future__ import annotations

import asyncio

from app.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.services.audience_service import AudienceEngine


async def run() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        engine_service = AudienceEngine(create_session_factory(engine), settings.hot_lead_threshold)
        contacts = await engine_service.recalculate_all()
        print(f"Audience profiles recalculated: {contacts}")
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
