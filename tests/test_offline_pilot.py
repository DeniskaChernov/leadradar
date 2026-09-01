from __future__ import annotations

from app.services.offline_pilot_service import OfflinePilotService


def test_offline_pilot_has_500_plus_labeled_cases_and_is_deterministic():
    service = OfflinePilotService()
    cases = service.build_corpus()
    first = service.evaluate(cases)
    second = service.evaluate(cases)

    assert first.corpus_size >= 500
    assert first.lead_cases >= 300
    assert first.rattan_cases >= 200
    assert first.deterministic_digest == second.deterministic_digest
    assert first.passed


async def test_offline_pilot_ingestion_is_idempotent(session_factory):
    service = OfflinePilotService()
    cases = service.build_corpus()
    ingestion = await service.verify_ingestion_idempotency(session_factory, cases)

    assert ingestion.first_created == len(cases)
    assert ingestion.retry_created == 0
    assert ingestion.comments == len(cases)
    assert ingestion.public_signals == len(cases)
    assert ingestion.evidence == len(cases)
    assert ingestion.duplicate_records == 0
