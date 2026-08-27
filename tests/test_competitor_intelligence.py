from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from app.web.queries import WebQueryService
from tests.test_contact_service import make_comment, make_post
from tests.test_lead_service import StaticAnalyzer


async def test_competitor_intelligence_uses_observed_commercial_data(session_factory):
    contacts = ContactService(session_factory)
    leads = LeadService(session_factory, StaticAnalyzer(), hot_threshold=70)
    first = await contacts.persist_signal(make_post(), make_comment("intel-first"))
    second_comment = make_comment("intel-second").model_copy(
        update={
            "platform_user_id": "buyer-2",
            "username": "buyer_two",
            "display_name": "Buyer Two",
            "profile_url": "https://www.instagram.com/buyer_two/",
            "text": "Сколько стоит?",
        }
    )
    second = await contacts.persist_signal(make_post(), second_comment)
    await leads.process_signal(first)
    await leads.process_signal(second)

    queries = WebQueryService(session_factory, hot_threshold=70)
    rows = await queries.competitors()
    aiko = next(item for item in rows if item["competitor"].normalized_handle == "aiko.uz")
    detail = await queries.competitor_intelligence(aiko["competitor"].id)

    assert aiko["comments"] == 2
    assert aiko["commercial"] == 2
    assert aiko["commercial_rate"] == 100.0
    assert aiko["unique_buyers"] == 2
    assert aiko["price_rate"] == 100.0
    assert detail is not None
    assert detail["public_response_observable"] is False
    assert detail["post_performance"][0]["commercial_comments"] == 2
    assert detail["post_performance"][0]["unique_buyers"] == 2
    assert detail["opportunities"][0]["intent"] == "PRICE"


async def test_overlap_network_counts_same_contact_once_per_pair(session_factory):
    contacts = ContactService(session_factory)
    leads = LeadService(session_factory, StaticAnalyzer(), hot_threshold=70)
    first = await contacts.persist_signal(make_post(), make_comment("overlap-aiko"))
    other_post = make_post().model_copy(
        update={
            "platform_post_id": "overlap-chinar-post",
            "competitor": "chinar.uz",
            "url": "https://www.instagram.com/reel/overlap-chinar-post/",
        }
    )
    second = await contacts.persist_signal(other_post, make_comment("overlap-chinar"))
    duplicate_source = await contacts.persist_signal(
        other_post, make_comment("overlap-chinar-again")
    )
    await leads.process_signal(first)
    await leads.process_signal(second)
    await leads.process_signal(duplicate_source)

    queries = WebQueryService(session_factory, hot_threshold=70)
    network = await queries.competitor_overlap_network()
    overview = await queries.competitor_intelligence_overview()
    rows = await queries.competitors()
    aiko = next(item for item in rows if item["competitor"].normalized_handle == "aiko.uz")

    assert len(network) == 1
    assert {network[0]["left"], network[0]["right"]} == {"aiko.uz", "chinar.uz"}
    assert network[0]["contacts"] == 1
    assert overview["multi_competitor"] == 1
    assert aiko["multi_competitor"] == 1
