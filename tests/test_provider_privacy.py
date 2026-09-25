import pytest
from sqlalchemy import select

from app.db.models import Comment, Evidence, PublicSignal
from app.providers.base import ProviderPrivacyError
from app.providers.brightdata import BrightDataProvider
from app.providers.fallback import FallbackInstagramProvider
from app.providers.public_data import ensure_public_source
from app.providers.scrapecreators import ScrapeCreatorsProvider
from app.services.contact_service import ContactService
from tests.test_providers import StubProvider


def test_scrapecreators_keeps_public_comment_from_private_author_without_contact_fields():
    comment = ScrapeCreatorsProvider.normalize_comment({
        "id": "public-comment", "text": "narxi?", "parent_comment_id": "parent-1",
        "email": "synthetic@example.invalid", "unexpected": {"private_note": "hidden"},
        "user": {
            "id": "42", "username": "public_author", "is_private": True,
            "phone_number": "synthetic", "email": "synthetic@example.invalid",
        },
    })
    assert comment.text == "narxi?"
    assert comment.username == "public_author"
    assert comment.parent_platform_comment_id == "parent-1"
    assert comment.raw_data == comment.model_dump(mode="json", exclude={"raw_data"})
    assert "synthetic" not in str(comment.raw_data)
    assert "is_private" not in str(comment.raw_data)


@pytest.mark.parametrize("provider,payload", [
    (ScrapeCreatorsProvider, {"id": "post-1", "code": "reel-1", "product_type": "clips"}),
    (BrightDataProvider, {"url": "https://www.instagram.com/reel/reel-1/", "post_id": "post-1"}),
])
def test_post_raw_payload_is_an_allowlist(provider, payload):
    post = provider.normalize_post({**payload, "email": "secret", "nested": {"phone": "secret"}}, "source")
    assert post.raw_data == post.model_dump(mode="json", exclude={"raw_data"})
    assert "secret" not in str(post.raw_data)


@pytest.mark.parametrize("flag", [
    {"is_private": True}, {"is_hidden": "true"}, {"is_public": False},
    {"owner": {"is_private": "1"}}, {"data": {"user": {"is_private": True}}},
])
def test_restricted_sources_are_rejected_without_retaining_payload(flag):
    with pytest.raises(ProviderPrivacyError):
        ensure_public_source(flag)
    with pytest.raises(ProviderPrivacyError):
        ScrapeCreatorsProvider.normalize_post({"id": "1", "code": "x", **flag}, "source")


def test_hidden_comment_is_rejected():
    with pytest.raises(ProviderPrivacyError):
        ScrapeCreatorsProvider.normalize_comment({
            "id": "1", "text": "hidden", "is_hidden": True,
            "user": {"username": "author"},
        })
    with pytest.raises(ProviderPrivacyError):
        BrightDataProvider.normalize_comment({"comment_id": "1", "is_hidden": True})


def test_brightdata_comment_drops_nested_unknown_fields():
    comment = BrightDataProvider.normalize_comment({
        "comment_id": "1", "comment_user": "author", "comment": "price?",
        "contact": {"email": "secret"}, "phone_number": "secret",
    })
    assert comment.text == "price?"
    assert "secret" not in str(comment.raw_data)


async def test_privacy_rejection_never_triggers_paid_fallback():
    class PrivateProvider(StubProvider):
        async def get_profile(self, handle):
            raise ProviderPrivacyError("restricted")

    fallback = StubProvider(fail=False)
    provider = FallbackInstagramProvider(PrivateProvider(fail=False), fallback)
    with pytest.raises(ProviderPrivacyError):
        await provider.get_profile("private_source")
    assert fallback.calls == 0


async def test_private_source_stops_before_comment_fetch():
    post = ScrapeCreatorsProvider.normalize_post({"id": "1", "code": "x"}, "source")
    post.raw_data["is_private"] = True
    provider = ScrapeCreatorsProvider("unused-test-key")
    try:
        with pytest.raises(ProviderPrivacyError):
            await provider.get_comment_batch(post)
    finally:
        await provider.aclose()


@pytest.mark.parametrize("private", [False, True])
async def test_profile_normalization_rejects_private_source_and_discards_extras(monkeypatch, private):
    provider = ScrapeCreatorsProvider("unused-test-key")

    async def payload(*args, **kwargs):
        return {"data": {"user": {
            "id": "1", "username": "source", "is_private": private,
            "phone_number": "secret", "email": "secret@example.invalid",
        }}}

    monkeypatch.setattr(provider, "_request_json", payload)
    try:
        if private:
            with pytest.raises(ProviderPrivacyError):
                await provider.get_profile("source")
        else:
            profile = await provider.get_profile("source")
            assert profile.username == "source"
            assert "secret" not in str(profile.raw_data)
    finally:
        await provider.aclose()


async def test_private_post_envelope_is_rejected(monkeypatch):
    provider = ScrapeCreatorsProvider("unused-test-key")

    async def payload(*args, **kwargs):
        return {"is_private": True, "data": {"xdt_shortcode_media": {"id": "1", "code": "x"}}}

    monkeypatch.setattr(provider, "_request_json", payload)
    try:
        with pytest.raises(ProviderPrivacyError):
            await provider.get_post("https://www.instagram.com/reel/x/", "source")
    finally:
        await provider.aclose()


async def test_forbidden_provider_fields_never_reach_persisted_evidence(session_factory):
    post = ScrapeCreatorsProvider.normalize_post({"id": "1", "code": "x"}, "source")
    comment = ScrapeCreatorsProvider.normalize_comment({
        "id": "comment-1", "text": "price?",
        "user": {"id": "1", "username": "buyer", "email": "secret@example.invalid"},
        "unexpected_payload": {"phone": "secret"},
    })
    service = ContactService(session_factory)
    persisted = await service.persist_signal(post, comment)
    repeated = await service.persist_signal(post, comment)
    assert persisted.created and not repeated.created
    async with session_factory() as session:
        for model in (Comment, PublicSignal, Evidence):
            rows = list(await session.scalars(select(model)))
            assert rows
            assert all("secret" not in str(row.raw_data) for row in rows)
