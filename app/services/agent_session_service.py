"""Grounded agent session: deterministic read-tool routing и синтез ответа из evidence."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.allowed_audience_registry import AllowedAudienceRegistry
from app.services.mcp_gateway_service import LeadRadarMCPGateway, ToolExecutionResult

READ_TOOL_NAMES = frozenset(
    {
        "lead.search",
        "lead.explain_score",
        "audience.dna",
        "competitor.opportunities",
        "rattan.company_analysis",
        "google.openings",
    }
)


@dataclass(frozen=True, slots=True)
class AgentToolInvocation:
    tool_name: str
    arguments: dict[str, Any]
    result: ToolExecutionResult


@dataclass(frozen=True, slots=True)
class AgentQueryResult:
    query: str
    answer: str
    evidence_ids: tuple[int, ...]
    tool_calls: tuple[AgentToolInvocation, ...]
    grounded: bool
    synthesis_mode: str


class AgentSessionService:
    """Offline-grounded agent: только read tools и факты из tool output."""

    _LEAD_ID_RE = re.compile(r"\blead[_\s-]?id[=:\s#]?(\d+)\b", re.IGNORECASE)
    _COMPETITOR_ID_RE = re.compile(r"\bcompetitor[_\s-]?id[=:\s#]?(\d+)\b", re.IGNORECASE)

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        hot_threshold: int,
        gateway: LeadRadarMCPGateway | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold
        self.gateway = gateway or LeadRadarMCPGateway.from_session_factory(
            session_factory,
            hot_threshold=hot_threshold,
        )

    async def query(
        self,
        text: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentQueryResult:
        normalized = (text or "").strip()
        if not normalized:
            raise ValueError("query is required")

        payload = dict(context or {})
        planned = self._plan_tools(normalized, payload)
        invocations: list[AgentToolInvocation] = []
        evidence_ids: set[int] = set()

        for tool_name, arguments in planned:
            result = await self.gateway.execute_tool_async(
                tool_name,
                arguments,
                approval_granted=False,
            )
            invocations.append(
                AgentToolInvocation(
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                )
            )
            if result.success:
                evidence_ids.update(self._extract_evidence_ids(result.output))

        answer = self._synthesize(normalized, invocations)
        return AgentQueryResult(
            query=normalized,
            answer=answer,
            evidence_ids=tuple(sorted(evidence_ids)),
            tool_calls=tuple(invocations),
            grounded=True,
            synthesis_mode="offline_deterministic",
        )

    def _plan_tools(self, query: str, context: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        lowered = query.lower()
        lead_id = self._optional_int(context.get("lead_id")) or self._match_int(
            self._LEAD_ID_RE, query
        )
        competitor_id = self._optional_int(context.get("competitor_id")) or self._match_int(
            self._COMPETITOR_ID_RE, query
        )
        segment_slug = str(context.get("segment_slug") or "").strip().lower() or self._match_segment_slug(
            lowered
        )
        company_name = str(context.get("company_name") or "").strip()
        if not company_name and any(token in lowered for token in ("ротанг", "rattan", "компан")):
            company_name = self._extract_company_hint(query)

        if lead_id is not None:
            return [("lead.explain_score", {"lead_id": lead_id})]

        if segment_slug:
            return [("audience.dna", {"segment_slug": segment_slug})]

        if competitor_id is not None or any(
            token in lowered for token in ("конкурент", "competitor", "спрос", "opportunit")
        ):
            if competitor_id is not None:
                return [("competitor.opportunities", {"competitor_id": competitor_id})]

        if company_name or any(token in lowered for token in ("ротанг", "rattan")):
            return [("rattan.company_analysis", {"company_name": company_name})]

        if any(token in lowered for token in ("открыт", "opening", "venue", "заведен")):
            status = str(context.get("status") or "PENDING_REVIEW")
            return [("google.openings", {"status": status})]

        if any(
            token in lowered
            for token in (
                "что предложить",
                "покажи лид",
                "показать лид",
                "найди лид",
                "список лид",
                "show lead",
                "list lead",
            )
        ):
            return [("lead.search", {"query": ""})]

        if any(token in lowered for token in ("скор", "score", "explain", "объясни", "лид", "lead")):
            if lead_id is not None:
                return [("lead.explain_score", {"lead_id": lead_id})]

        return [("lead.search", {"query": query})]

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        return int(value)

    @staticmethod
    def _match_int(pattern: re.Pattern[str], text: str) -> int | None:
        match = pattern.search(text)
        if match is None:
            return None
        return int(match.group(1))

    @classmethod
    def _match_segment_slug(cls, lowered_query: str) -> str:
        for definition in AllowedAudienceRegistry.list_active():
            if definition.slug in lowered_query:
                return definition.slug
        return ""

    @staticmethod
    def _extract_company_hint(query: str) -> str:
        cleaned = query.strip()
        for prefix in ("ротанг", "rattan", "компания", "company"):
            if cleaned.lower().startswith(prefix):
                return cleaned[len(prefix) :].strip(" :—-")
        return cleaned

    @staticmethod
    def _extract_evidence_ids(output: Any) -> set[int]:
        if not isinstance(output, dict):
            return set()
        ids: set[int] = set()
        raw = output.get("evidence_ids")
        if isinstance(raw, list):
            ids.update(int(item) for item in raw)
        for key in ("leads", "audience_memberships", "sample_questions"):
            rows = output.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("evidence_ids"), list):
                    ids.update(int(item) for item in row["evidence_ids"])
        nested = output.get("audience_memberships")
        if isinstance(nested, list):
            for row in nested:
                if isinstance(row, dict) and isinstance(row.get("evidence_ids"), list):
                    ids.update(int(item) for item in row["evidence_ids"])
        return ids

    def _synthesize(self, query: str, invocations: Sequence[AgentToolInvocation]) -> str:
        if not invocations:
            return (
                "Нет подключённых read tools для этого запроса. "
                "Ответ может быть только на основе данных Lead Radar."
            )

        invocation = invocations[0]
        result = invocation.result
        if not result.success:
            error = result.output.get("error") if isinstance(result.output, dict) else None
            if error == "NOT_CONNECTED":
                return (
                    "Read tool ещё не подключён к реальным данным. "
                    "Ответ без evidence не формируется."
                )
            if isinstance(result.output, dict) and result.output.get("error"):
                return f"Tool `{invocation.tool_name}` вернул ошибку: {result.output['error']}."
            return f"Tool `{invocation.tool_name}` не выполнен."

        output = result.output
        if not isinstance(output, dict):
            return "Tool вернул неструктурированный результат; синтез пропущен."

        if invocation.tool_name == "lead.search":
            return self._synthesize_lead_search(query, output)
        if invocation.tool_name == "lead.explain_score":
            return self._synthesize_lead_explain(output)
        if invocation.tool_name == "audience.dna":
            return self._synthesize_audience_dna(output)
        if invocation.tool_name == "competitor.opportunities":
            return self._synthesize_competitor(output)
        if invocation.tool_name == "rattan.company_analysis":
            return self._synthesize_rattan(output)
        if invocation.tool_name == "google.openings":
            return self._synthesize_openings(output)
        return "Данные получены из read tool, но для этого tool нет шаблона синтеза."

    @staticmethod
    def _synthesize_lead_search(query: str, output: dict[str, Any]) -> str:
        leads = output.get("leads") or []
        if not leads:
            return (
                f"По запросу «{query or 'последние'}» подтверждённых лидов в базе не найдено. "
                "Каталог, скидки и наличие не выводятся без evidence."
            )
        lines = [
            f"Найдено лидов: {output.get('count', len(leads))}.",
            "Ответ основан только на persisted leads и evidence_ids из БД.",
        ]
        for item in leads[:5]:
            evidence = item.get("evidence_ids") or []
            evidence_text = ", ".join(str(value) for value in evidence[:6]) or "нет"
            lines.append(
                f"- @{item.get('username')} · score {item.get('score')} · "
                f"{item.get('intent')} · {item.get('competitor')} · evidence: {evidence_text}"
            )
        if len(leads) > 5:
            lines.append(f"… ещё {len(leads) - 5} лидов.")
        lines.append(
            "Каталог, остатки и сроки поставки не подставляются автоматически — "
            "проверьте подтверждённый каталог перед предложением."
        )
        return "\n".join(lines)

    @staticmethod
    def _synthesize_lead_explain(output: dict[str, Any]) -> str:
        if output.get("error") == "NOT_FOUND":
            return f"Lead #{output.get('lead_id')} не найден."
        evidence = output.get("evidence_ids") or []
        memberships = output.get("audience_memberships") or []
        lines = [
            f"Lead #{output.get('lead_id')} (@{output.get('username')}) · score {output.get('score')}.",
            f"Intent: {output.get('intent')} · category: {output.get('product_category') or '—'}.",
            f"Competitor: {output.get('competitor')}.",
            f"Evidence IDs: {', '.join(str(item) for item in evidence) or 'нет'}.",
        ]
        analysis = output.get("analysis_details") or {}
        if analysis:
            lines.append(f"Analysis keys: {', '.join(sorted(analysis))}.")
        if memberships:
            lines.append("Audience memberships:")
            for item in memberships[:5]:
                lines.append(
                    f"- {item.get('segment_slug')} · confidence {item.get('confidence')} · "
                    f"evidence {item.get('evidence_ids')}"
                )
        excerpt = output.get("comment_excerpt")
        if excerpt:
            lines.append(f"Comment excerpt: {excerpt}")
        return "\n".join(lines)

    @staticmethod
    def _synthesize_audience_dna(output: dict[str, Any]) -> str:
        if output.get("error") == "AUDIENCE_NOT_ALLOWED":
            allowed = ", ".join(output.get("allowed_slugs") or [])
            return f"Сегмент `{output.get('segment_slug')}` не разрешён. ACTIVE slugs: {allowed}."
        if output.get("error") == "NOT_FOUND":
            return f"Сегмент `{output.get('segment_slug')}` не найден в БД."
        top_products = output.get("top_products") or []
        top_intents = output.get("top_intents") or []
        product_text = ", ".join(
            AgentSessionService._format_bucket(item) for item in top_products[:5]
        ) or "—"
        intent_text = ", ".join(
            AgentSessionService._format_bucket(item) for item in top_intents[:5]
        ) or "—"
        evidence = output.get("evidence_ids") or []
        return "\n".join(
            [
                f"Audience DNA · {output.get('segment_name')} ({output.get('segment_slug')}).",
                f"Members: {output.get('members', 0)}.",
                f"Top intents: {intent_text}.",
                f"Top products: {product_text}.",
                f"Evidence IDs: {', '.join(str(item) for item in evidence[:12]) or 'нет'}.",
            ]
        )

    @staticmethod
    def _synthesize_competitor(output: dict[str, Any]) -> str:
        if output.get("error") == "NOT_FOUND":
            return f"Competitor #{output.get('competitor_id')} не найден."
        opportunities = output.get("opportunities") or []
        questions = output.get("sample_questions") or []
        lines = [
            f"Competitor @{output.get('competitor')} · commercial comments: "
            f"{output.get('commercial_comments', 0)}.",
            f"Demand gap score: {output.get('demand_gap_score')}.",
        ]
        if opportunities:
            lines.append("Opportunities:")
            for item in opportunities[:5]:
                if isinstance(item, dict):
                    lines.append(f"- {item.get('title') or item.get('type')}: {item.get('summary') or item}")
                else:
                    lines.append(f"- {item}")
        if questions:
            lines.append("Sample demand:")
            for item in questions[:5]:
                lines.append(
                    f"- @{item.get('username')} · {item.get('intent')} · score {item.get('score')}"
                )
        evidence = output.get("evidence_ids") or []
        lines.append(f"Evidence IDs: {', '.join(str(value) for value in evidence[:12]) or 'нет'}.")
        return "\n".join(lines)

    @staticmethod
    def _synthesize_rattan(output: dict[str, Any]) -> str:
        companies = output.get("companies") or []
        company_lines = ", ".join(
            f"@{item.get('handle')}" for item in companies[:8]
        ) or "—"
        layers = output.get("layers") or {}
        roles = output.get("roles") or {}
        layer_text = ", ".join(f"{key}: {value}" for key, value in layers.items()) or "—"
        role_text = ", ".join(f"{key}: {value}" for key, value in roles.items()) or "—"
        evidence = output.get("evidence_ids") or []
        return "\n".join(
            [
                f"Rattan analysis · filter: {output.get('company_name') or 'ALL'}.",
                f"Commercial signals: {output.get('commercial_signals', 0)}.",
                f"Companies: {company_lines}.",
                f"Layers: {layer_text}.",
                f"Roles: {role_text}.",
                f"Evidence IDs: {', '.join(str(item) for item in evidence[:12]) or 'нет'}.",
            ]
        )

    @staticmethod
    def _synthesize_openings(output: dict[str, Any]) -> str:
        openings = output.get("openings") or []
        if not openings:
            return f"Opening queue `{output.get('status')}` пуста."
        lines = [f"Opening queue `{output.get('status')}` · count {output.get('count', len(openings))}."]
        for item in openings[:8]:
            lines.append(
                f"- {item.get('place_name')} ({item.get('place_type')}) · "
                f"{item.get('city') or '—'} · confidence {item.get('confidence')}"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_bucket(item: Any) -> str:
        if isinstance(item, dict):
            return f"{item.get('name')} ({item.get('count')})"
        if isinstance(item, (list, tuple)) and len(item) == 2:
            return f"{item[0]} ({item[1]})"
        return str(item)

    @staticmethod
    def _format_bucket(item: Any) -> str:
        if isinstance(item, dict):
            return f"{item.get('name')} ({item.get('count')})"
        if isinstance(item, (list, tuple)) and len(item) == 2:
            return f"{item[0]} ({item[1]})"
        return str(item)
