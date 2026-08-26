from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from openai import AsyncOpenAI

from app.schemas.leads import LeadAnalysis

logger = logging.getLogger(__name__)


class AIAnalysisError(RuntimeError):
    """The AI analysis could not be completed and should be retried later."""


@dataclass(frozen=True, slots=True)
class PreviousSignal:
    competitor: str
    post_caption: str
    comment: str
    discovered_at: str


@dataclass(frozen=True, slots=True)
class LeadAnalysisContext:
    competitor: str
    post_caption: str
    comment: str
    username: str
    previous_signals: list[PreviousSignal]
    previous_interests: list[str]


class LeadAnalyzer(Protocol):
    async def analyze(self, context: LeadAnalysisContext) -> LeadAnalysis: ...


class OpenAILeadAnalyzer:
    def __init__(self, api_key: str, model: str, client: Any | None = None) -> None:
        self.model = model
        self.client = client or AsyncOpenAI(api_key=api_key)

    async def analyze(self, context: LeadAnalysisContext) -> LeadAnalysis:
        payload = {
            **asdict(context),
            "catalog_scope": [
                "wicker furniture",
                "artificial rattan furniture",
                "dining sets",
                "tables",
                "chairs",
                "kitchen and dining furniture",
                "garden and terrace furniture",
                "cafe, restaurant and HoReCa furniture",
            ],
        }
        system_prompt = (
            "You qualify public Instagram comments for a furniture seller. "
            "Understand Russian, Uzbek Latin, Uzbek Cyrillic, and mixed phrases. "
            "Score commercial purchase intent from 0 to 100. Consider the reel CTA, "
            "product relevance, specificity, and prior signals. A '+' is commercial only "
            "when the post CTA asks for '+' to receive price/catalog/contact. "
            "Reaction or engagement-only comments are not leads. Return the requested schema."
        )
        try:
            response = await self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False, default=str),
                    },
                ],
                text_format=LeadAnalysis,
            )
            parsed = response.output_parsed
            if parsed is None:
                raise AIAnalysisError("OpenAI returned no parsed lead analysis")
            if isinstance(parsed, LeadAnalysis):
                return parsed
            return LeadAnalysis.model_validate(parsed)
        except AIAnalysisError:
            raise
        except Exception as exc:
            logger.exception("ai_analysis_failed error_type=%s", type(exc).__name__)
            raise AIAnalysisError("OpenAI lead analysis failed") from exc


class UnavailableLeadAnalyzer:
    async def analyze(self, context: LeadAnalysisContext) -> LeadAnalysis:
        raise AIAnalysisError("OPENAI_API_KEY is not configured")

