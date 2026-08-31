"""Meta Ads Marketing API adapter with fail-closed gate."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

_GRAPH_API_VERSION = "v22.0"


class MetaAdsService:
    """Connector к Meta Graph API; без unlock и credentials остаётся NOT_CONNECTED."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def connected(self) -> bool:
        return self.settings.meta_ads_live_enabled

    @staticmethod
    def not_connected_message() -> str:
        return (
            "Meta Ads connector is not configured. "
            "Set META_ADS_ACCESS_TOKEN, META_ADS_AD_ACCOUNT_ID, META_ADS_LIVE_CALLS_ENABLED=true "
            "and EXTERNAL_LIVE_UNLOCK=ALLOW_EXTERNAL_CALLS with EXTERNAL_KILL_SWITCH=false."
        )

    async def create_campaign_draft(self, recipe_type: str, budget_usd: float) -> dict[str, Any]:
        if not self.connected:
            return {"error": "NOT_CONNECTED", "message": self.not_connected_message()}

        recipe_type = recipe_type.strip() or "GENERIC"
        if budget_usd <= 0:
            return {"error": "INVALID_ARGUMENTS", "message": "budget_usd must be positive"}

        account_id = self.settings.meta_ads_ad_account_id.removeprefix("act_")
        daily_budget_cents = max(int(budget_usd * 100), 100)
        campaign_name = f"Lead Radar · {recipe_type}"

        async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
            campaign = await self._post_graph(
                client,
                f"act_{account_id}/campaigns",
                {
                    "name": campaign_name,
                    "objective": "OUTCOME_LEADS",
                    "status": "PAUSED",
                    "special_ad_categories": "[]",
                    "is_adset_budget_sharing_enabled": "false",
                },
            )
            if "error" in campaign:
                return campaign

            campaign_id = str(campaign["id"])
            adset = await self._post_graph(
                client,
                f"act_{account_id}/adsets",
                {
                    "name": f"{campaign_name} · AdSet",
                    "campaign_id": campaign_id,
                    "status": "PAUSED",
                    "daily_budget": str(daily_budget_cents),
                    "billing_event": "IMPRESSIONS",
                    "optimization_goal": "LEAD_GENERATION",
                    "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                    "targeting": '{"geo_locations":{"countries":["UZ"]}}',
                },
            )
            if "error" in adset:
                return adset

        return {
            "campaign_id": campaign_id,
            "adset_id": str(adset["id"]),
            "status": "PAUSED",
            "recipe_type": recipe_type,
            "daily_budget_usd": budget_usd,
        }

    async def _post_graph(
        self,
        client: httpx.AsyncClient,
        path: str,
        payload: dict[str, str],
    ) -> dict[str, Any]:
        response = await client.post(
            f"https://graph.facebook.com/{_GRAPH_API_VERSION}/{path}",
            data={
                **payload,
                "access_token": self.settings.meta_ads_access_token,
            },
        )
        try:
            body = response.json()
        except ValueError:
            body = {"error": "META_HTTP_ERROR", "message": response.text[:500]}
        if response.status_code >= 400 or "error" in body:
            error = body.get("error", body)
            message = error.get("message") if isinstance(error, dict) else str(error)
            logger.warning(
                "meta_ads_graph_error path=%s status=%s message=%s",
                path,
                response.status_code,
                message,
            )
            return {
                "error": "META_API_ERROR",
                "message": message or f"Meta Graph API HTTP {response.status_code}",
            }
        return body
