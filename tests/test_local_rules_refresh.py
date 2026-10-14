from httpx import ASGITransport, AsyncClient

from app.db.models import AIRequest, AIRequestStatus, Lead, LeadStatus
from app.services.ai_service import HybridLeadAnalyzer, RuleBasedLeadAnalyzer
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from tests.test_contact_service import make_comment, make_post
from tests.test_free_pending_review import history, make_app


async def stale_local_lead(factory, index="local"):
    service = LeadService(factory, HybridLeadAnalyzer(RuleBasedLeadAnalyzer(), None, mode="hybrid"),
                          70, rules_version="3.4")
    signal = await ContactService(factory).persist_signal(
        make_post().model_copy(update={"caption": "Плетёные кресла"}),
        make_comment(f"refresh-{index}").model_copy(update={"text": "Цена?"}))
    result = await service.process_signal(signal)
    async with factory() as session:
        lead = await session.get(Lead, result.lead_id)
        lead.analysis_details = {**lead.analysis_details, "rules_version": "3.3"}
        lead.lead_score = 7
        await session.commit()
    return service, result.lead_id


async def test_refresh_is_free_dry_run_then_idempotent_and_preserves_history(session_factory):
    service, lead_id = await stale_local_lead(session_factory)
    before = await history(session_factory)
    preview = await service.refresh_local_rules()
    assert preview["matched"] == [lead_id] and not preview["updated"]
    assert await history(session_factory) == before
    first = await service.refresh_local_rules(dry_run=False)
    after = await history(session_factory)
    assert first["updated"] == [lead_id] and after[:len(before)] == before
    assert len(after) == len(before) + 1
    assert not (await service.refresh_local_rules(dry_run=False))["matched"]
    assert await history(session_factory) == after
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead.lead_score >= 70 and lead.analysis_details["rules_version"] == "3.4"
        assert lead.ai_source == "local_rules"


async def test_paid_and_manager_decisions_are_not_automatically_refreshed(session_factory):
    service, lead_id = await stale_local_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.ai_source = "openai_or_cache"
        await session.commit()
    before = await history(session_factory)
    assert not (await service.refresh_local_rules(dry_run=False))["matched"]
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.ai_source = "local_rules"
        lead.assigned_manager_telegram_id = 1001
        await session.commit()
    assert not (await service.refresh_local_rules(dry_run=False))["matched"]
    assert await history(session_factory) == before


async def test_manager_assignment_between_preview_and_final_write_takes_precedence(file_session_factory):
    factory = file_session_factory
    service, lead_id = await stale_local_lead(factory)
    before = await history(factory)

    class AssignmentDuringSnapshot:
        async def snapshot(self, _contact_id):
            async with factory() as session:
                lead = await session.get(Lead, lead_id)
                lead.assigned_manager_telegram_id = 1001
                lead.status = LeadStatus.TAKEN
                await session.commit()

    service.change_detector = AssignmentDuringSnapshot()
    assert not (await service.refresh_local_rules(dry_run=False))["updated"]
    assert await history(factory) == before
    async with factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead.status == LeadStatus.TAKEN and lead.lead_score == 7
        assert lead.analysis_details["rules_version"] == "3.3"


async def test_claimed_ai_work_blocks_refresh_of_an_old_local_result(session_factory):
    service, lead_id = await stale_local_lead(session_factory)
    async with session_factory() as session:
        session.add(AIRequest(lead_id=lead_id, context_fingerprint="d" * 64, model="test",
                              status=AIRequestStatus.CLAIMED))
        await session.commit()
    before = await history(session_factory)
    assert not (await service.refresh_local_rules(dry_run=False))["matched"]
    assert await history(session_factory) == before


async def test_free_button_refreshes_old_local_rules_and_reports_it(session_factory):
    _, lead_id = await stale_local_lead(session_factory)
    app = await make_app(session_factory, openai_allowed=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post('/api/leads/retry-pending-local', json={"limit": 100})
        second = await client.post('/api/leads/retry-pending-local', json={"limit": 100})
    assert first.status_code == second.status_code == 200
    assert first.json()["processed"] == first.json()["rules_refreshed"] == 1
    assert first.json()["local_recovered"] == 0 and not first.json()["openai_used"]
    assert second.json()["processed"] == 0
    async with session_factory() as session:
        assert (await session.get(Lead, lead_id)).analysis_details["rules_version"] == "3.4"
