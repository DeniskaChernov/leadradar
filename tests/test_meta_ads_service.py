"""Tests for MetaAdsService fail-closed gate."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.services.meta_ads_service import MetaAdsService


def _live_settings(**changes) -> Settings:
    values = {
        "external_kill_switch": False,
        "external_live_unlock": "ALLOW_EXTERNAL_CALLS",
        "meta_ads_access_token": "token",
        "meta_ads_ad_account_id": "123456",
        "meta_ads_live_calls_enabled": True,
    }
    values.update(changes)
    return Settings(_env_file=None, **values)


@pytest.mark.asyncio
async def test_meta_ads_not_connected_when_kill_switch_enabled():
    service = MetaAdsService(
        Settings(
            _env_file=None,
            external_kill_switch=True,
            meta_ads_access_token="token",
            meta_ads_ad_account_id="123456",
            meta_ads_live_calls_enabled=True,
        )
    )
    result = await service.create_campaign_draft("NARROW", 100.0)
    assert result["error"] == "NOT_CONNECTED"


@pytest.mark.asyncio
async def test_meta_ads_rejects_non_positive_budget():
    service = MetaAdsService(_live_settings())
    result = await service.create_campaign_draft("NARROW", 0)
    assert result["error"] == "INVALID_ARGUMENTS"


@pytest.mark.asyncio
async def test_meta_ads_post_graph_parses_success_payload():
    service = MetaAdsService(_live_settings())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "cmp_1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await service._post_graph(client, "act_123/campaigns", {"name": "x"})
    assert payload == {"id": "cmp_1"}


@pytest.mark.asyncio
async def test_meta_ads_create_custom_audience_not_connected():
    service = MetaAdsService(Settings(_env_file=None, meta_ads_live_calls_enabled=False))
    result = await service.create_custom_audience(name="Test", phone_hashes=["a" * 64])
    assert result["error"] == "NOT_CONNECTED"


@pytest.mark.asyncio
async def test_meta_ads_create_custom_audience_paused_upload(monkeypatch):
    service = MetaAdsService(_live_settings())
    calls: list[str] = []

    async def fake_post_graph(client, path, payload):
        calls.append(path)
        if path.endswith("/customaudiences"):
            return {"id": "aud_1"}
        if path.endswith("/users"):
            return {"num_received": 1, "num_invalid_entries": 0}
        return {"error": "META_API_ERROR", "message": f"unexpected {path}"}

    monkeypatch.setattr(service, "_post_graph", fake_post_graph)
    result = await service.create_custom_audience(
        name="Lead Radar · dining",
        phone_hashes=["b" * 64],
        description="test",
    )
    assert result["audience_id"] == "aud_1"
    assert result["status"] == "PAUSED"
    assert result["uploaded"] == 1
    assert any(path.endswith("/customaudiences") for path in calls)
    assert any(path.endswith("/users") for path in calls)


@pytest.mark.asyncio
async def test_meta_ads_create_custom_audience_rejects_invalid_entries(monkeypatch):
    service = MetaAdsService(_live_settings())

    async def fake_post_graph(client, path, payload):
        if path.endswith("/customaudiences"):
            return {"id": "aud_bad"}
        if path.endswith("/users"):
            return {"num_received": 0, "num_invalid_entries": 1}
        return {"error": "META_API_ERROR", "message": f"unexpected {path}"}

    monkeypatch.setattr(service, "_post_graph", fake_post_graph)
    result = await service.create_custom_audience(
        name="Lead Radar · bad",
        phone_hashes=["c" * 64],
    )
    assert result["error"] == "META_INVALID_ENTRIES"
    assert result["audience_id"] == "aud_bad"
    assert result.get("partial") is True