"""Meta Ads Marketing API adapter with fail-closed gate."""

from __future__ import annotations

import json
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

    async def create_custom_audience(
        self,
        *,
        name: str,
        phone_hashes: list[str],
        description: str = "",
    ) -> dict[str, Any]:
        """Создаёт PAUSED Custom Audience и загружает SHA-256 телефоны (first-party only)."""
        if not self.connected:
            return {"error": "NOT_CONNECTED", "message": self.not_connected_message()}

        cleaned_name = name.strip()
        if not cleaned_name:
            return {"error": "INVALID_ARGUMENTS", "message": "name is required"}
        hashes = [item.strip().lower() for item in phone_hashes if item and item.strip()]
        if not hashes:
            return {
                "error": "INVALID_ARGUMENTS",
                "message": "phone_hashes must contain at least one SHA-256 value",
            }
        if any(len(item) != 64 or any(ch not in "0123456789abcdef" for ch in item) for item in hashes):
            return {
                "error": "INVALID_ARGUMENTS",
                "message": "phone_hashes must be lowercase SHA-256 hex digests",
            }

        account_id = self.settings.meta_ads_ad_account_id.removeprefix("act_")
        async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
            audience = await self._post_graph(
                client,
                f"act_{account_id}/customaudiences",
                {
                    "name": cleaned_name,
                    "subtype": "CUSTOM",
                    "description": description.strip() or cleaned_name,
                    "customer_file_source": "USER_PROVIDED_ONLY",
                },
            )
            if "error" in audience:
                return audience
            audience_id = str(audience["id"])
            users = await self._post_graph(
                client,
                f"{audience_id}/users",
                {
                    "payload": json.dumps(
                        {
                            "schema": ["PHONE_SHA256"],
                            "data": [[item] for item in hashes],
                        }
                    ),
                },
            )
            if "error" in users:
                return {
                    **users,
                    "audience_id": audience_id,
                    "status": "PAUSED",
                    "partial": True,
                }

        return {
            "audience_id": audience_id,
            "status": "PAUSED",
            "uploaded": len(hashes),
            "num_received": users.get("num_received"),
            "num_invalid_entries": users.get("num_invalid_entries"),
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
