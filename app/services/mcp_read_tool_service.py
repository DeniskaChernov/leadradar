"""DB-backed read handlers для LeadRadar MCP tools."""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Evidence, PublicSignal
from app.services.allowed_audience_registry import AllowedAudienceRegistry
from app.services.audience_membership_resolver import AudienceMembershipResolver
from app.services.product_catalog_service import ProductCatalogService
from app.web.queries import WebQueryService


class MCPReadToolService:
    """Выполняет read-only MCP tools против SQLite без внешних вызовов."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        hot_threshold: int,
    ) -> None:
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold
        self.queries = WebQueryService(session_factory, hot_threshold)
        self.catalog_service = ProductCatalogService(session_factory)
        self.membership_resolver = AudienceMembershipResolver(session_factory)

    async def dispatch(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "lead.search":
            contact_id = arguments.get("contact_id")
            return await self.lead_search(
                str(arguments.get("query") or ""),
                contact_id=int(contact_id) if contact_id not in (None, "") else None,
            )
        if tool_name == "lead.explain_score":
            lead_id = int(arguments["lead_id"])
            return await self.lead_explain_score(lead_id)
        if tool_name == "catalog.recommend":
            return await self.catalog_recommend(int(arguments["lead_id"]))
        if tool_name == "audience.dna":
            return await self.audience_dna(str(arguments.get("segment_slug") or ""))
        if tool_name == "competitor.opportunities":
            return await self.competitor_opportunities(int(arguments["competitor_id"]))
        if tool_name == "rattan.company_analysis":
            return await self.rattan_company_analysis(str(arguments.get("company_name") or ""))
        if tool_name == "google.openings":
            return await self.google_openings(str(arguments.get("status") or "PENDING_REVIEW"))
        raise ValueError(f"Unsupported read tool: {tool_name}")

    async def lead_search(self, query: str, *, contact_id: int | None = None) -> dict[str, Any]:
        rows = await self.queries.leads(q=query, contact_id=contact_id, limit=20)
        leads: list[dict[str, Any]] = []
        evidence_ids: list[int] = []
        for lead, contact, comment, competitor, _post, deal in rows:
            ids = await self._evidence_ids_for_comment(comment.id)
            evidence_ids.extend(ids)
            leads.append(
                {
                    "lead_id": lead.id,
                    "contact_id": contact.id,
                    "username": contact.username,
                    "score": lead.lead_score,
                    "status": lead.status.value,
                    "intent": lead.intent,
                    "product_category": lead.product_category,
                    "competitor": competitor.normalized_handle,
                    "comment_excerpt": (comment.text or "")[:160],
                    "is_hot": lead.lead_score >= self.hot_threshold,
                    "deal_status": deal.status.value if deal is not None else None,
                    "evidence_ids": ids,
                }
            )
        return {
            "query": query,
            "count": len(leads),
            "leads": leads,
            "evidence_ids": sorted(set(evidence_ids)),
        }

    async def lead_explain_score(self, lead_id: int) -> dict[str, Any]:
        detail = await self.queries.lead_detail(lead_id)
        if detail is None:
            return {"error": "NOT_FOUND", "lead_id": lead_id}
        lead = detail["lead"]
        contact = detail["contact"]
        comment = detail["comment"]
        competitor = detail["competitor"]
        evidence_ids = await self._evidence_ids_for_comment(comment.id)
        analysis = lead.analysis_details or {}
        membership = await self.membership_resolver.resolve_contact(contact.id)
        return {
            "lead_id": lead.id,
            "contact_id": contact.id,
            "username": contact.username,
            "score": lead.lead_score,
            "status": lead.status.value,
            "intent": lead.intent,
            "product_category": lead.product_category,
            "competitor": competitor.normalized_handle,
            "comment_excerpt": (comment.text or "")[:240],
            "analysis_details": {
                key: analysis[key]
                for key in (
                    "funnel_stage",
                    "commercial_quality",
                    "buyer_role",
                    "v2_buyer_role",
                    "rattan_taxonomy",
                )
                if key in analysis
            },
            "evidence_ids": evidence_ids,
            "audience_memberships": [
                {
                    "segment_slug": item.segment_slug,
                    "segment_name": item.segment_name,
                    "confidence": item.confidence,
                    "evidence_ids": list(item.evidence_ids),
                }
                for item in (membership.memberships if membership else ())
            ],
        }

    async def catalog_recommend(self, lead_id: int) -> dict[str, Any]:
        detail = await self.queries.lead_detail(lead_id)
        if detail is None:
            return {"error": "NOT_FOUND", "lead_id": lead_id}
        lead = detail["lead"]
        recommendation = await self.catalog_service.recommend_for_lead(lead)
        evidence_ids = list(recommendation.evidence_ids)
        return {
            "lead_id": lead_id,
            "title": recommendation.title,
            "description": recommendation.description,
            "action_type": recommendation.action_type,
            "urgency": recommendation.urgency,
            "recommended_product_id": recommendation.recommended_product_id,
            "recommended_sku": recommendation.recommended_sku,
            "match_reasons": list(recommendation.match_reasons),
            "evidence_ids": evidence_ids,
        }

    async def audience_dna(self, segment_slug: str) -> dict[str, Any]:
        definition = AllowedAudienceRegistry.get(segment_slug)
        if definition is None:
            allowed = [item.slug for item in AllowedAudienceRegistry.list_active()]
            return {
                "error": "AUDIENCE_NOT_ALLOWED",
                "segment_slug": segment_slug,
                "allowed_slugs": allowed,
            }
        detail = await self.queries.audience_detail(segment_slug)
        if detail is None:
            return {"error": "NOT_FOUND", "segment_slug": segment_slug}
        segment = detail["segment"]
        members = detail.get("members") or []
        evidence_ids: set[int] = set()
        for membership, _contact, _intel in members:
            evidence_ids.update(membership.evidence_ids_json or [])
        return {
            "segment_slug": segment.slug,
            "segment_name": segment.name,
            "description": segment.description,
            "audience_family": segment.audience_family,
            "members": len(members),
            "criteria": segment.criteria_json,
            "top_products": [
                {"name": name, "count": count} for name, count in (detail.get("top_products") or [])
            ],
            "top_intents": [
                {"name": name, "count": count} for name, count in (detail.get("top_intents") or [])
            ],
            "evidence_ids": sorted(evidence_ids),
        }

    async def competitor_opportunities(self, competitor_id: int) -> dict[str, Any]:
        data = await self.queries.competitor_intelligence(competitor_id)
        if data is None:
            return {"error": "NOT_FOUND", "competitor_id": competitor_id}
        questions = data.get("questions") or []
        evidence_ids: list[int] = []
        for item in questions[:10]:
            comment = item["comment"]
            evidence_ids.extend(await self._evidence_ids_for_comment(comment.id))
        return {
            "competitor_id": competitor_id,
            "competitor": data["competitor"].normalized_handle,
            "commercial_comments": data.get("stats", {}).get("commercial_comments", 0),
            "opportunities": data.get("opportunities") or [],
            "demand_gap_score": (data.get("gap") or {}).get("score"),
            "sample_questions": [
                {
                    "lead_id": item["lead"].id,
                    "username": item["contact"].username,
                    "intent": item["lead"].intent,
                    "score": item["lead"].lead_score,
                    "comment_excerpt": (item["comment"].text or "")[:160],
                }
                for item in questions[:8]
            ],
            "evidence_ids": sorted(set(evidence_ids)),
        }

    async def rattan_company_analysis(self, company_name: str) -> dict[str, Any]:
        workspace = await self.queries.rattan_workspace()
        needle = company_name.strip().lower()
        companies = workspace["rattan_companies"]
        if needle:
            companies = [
                item
                for item in companies
                if needle in item.normalized_handle.lower()
                or needle in (item.display_name or "").lower()
            ]
        matched_rows = workspace["rattan_rows"]
        if needle:
            matched_rows = [
                row
                for row in matched_rows
                if needle in row[3].normalized_handle.lower()
                or needle in (row[3].display_name or "").lower()
            ]
        evidence_ids = sorted({row[5].id for row in matched_rows})
        roles: dict[str, int] = {}
        layers: dict[str, int] = {}
        for _lead, _comment, _contact, _competitor, _signal, evidence in matched_rows:
            taxonomy = (evidence.raw_data or {}).get("rattan_taxonomy") or {}
            layer = str(taxonomy.get("layer") or "NONE")
            role = str(taxonomy.get("role") or "UNKNOWN")
            layers[layer] = layers.get(layer, 0) + 1
            if role != "UNKNOWN":
                roles[role] = roles.get(role, 0) + 1
        return {
            "company_name": company_name or None,
            "companies": [
                {
                    "id": item.id,
                    "handle": item.normalized_handle,
                    "display_name": item.display_name,
                }
                for item in companies[:10]
            ],
            "commercial_signals": len(matched_rows),
            "layers": layers,
            "roles": roles,
            "evidence_ids": evidence_ids,
        }

    async def google_openings(self, status: str) -> dict[str, Any]:
        from app.services.place_opening_service import PlaceOpeningService

        service = PlaceOpeningService(self.session_factory)
        if status.upper() == "PENDING_REVIEW":
            rows = await service.get_review_queue()
        else:
            async with self.session_factory() as session:
                from app.db.models import OpeningSignal

                rows = list(
                    await session.scalars(
                        select(OpeningSignal)
                        .where(OpeningSignal.review_status == status.upper())
                        .order_by(desc(OpeningSignal.confidence), desc(OpeningSignal.id))
                        .limit(20)
                    )
                )
        return {
            "status": status.upper(),
            "count": len(rows),
            "openings": [
                {
                    "opening_id": item.id,
                    "place_name": item.place_name,
                    "place_type": item.place_type,
                    "city": item.city,
                    "opening_timeline": item.opening_timeline,
                    "confidence": item.confidence,
                    "review_status": item.review_status,
                    "contact_id": item.contact_id,
                    "lead_id": item.lead_id,
                }
                for item in rows
            ],
            "evidence_ids": [],
        }

    async def _evidence_ids_for_comment(self, comment_id: int) -> list[int]:
        async with self.session_factory() as session:
            signal = await session.scalar(
                select(PublicSignal.id).where(PublicSignal.comment_id == comment_id)
            )
            if signal is None:
                return []
            return list(
                await session.scalars(
                    select(Evidence.id)
                    .where(Evidence.public_signal_id == signal)
                    .order_by(Evidence.id)
                )
            )
