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
async def test_meta_ads_post_graph_surfaces_graph_errors():
    service = MetaAdsService(_live_settings())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Invalid token"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await service._post_graph(client, "act_123/campaigns", {"name": "x"})
    assert payload["error"] == "META_API_ERROR"
    assert "Invalid token" in payload["message"]
