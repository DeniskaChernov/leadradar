from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AnalysisCache
from app.schemas.leads import Intent, LeadAnalysis
from app.services.usage_service import ExternalBudgetExceeded, ExternalUsageService

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
    known_customer_context: dict[str, str | int | None] = field(default_factory=dict)


class LeadAnalyzer(Protocol):
    async def analyze(self, context: LeadAnalysisContext) -> LeadAnalysis: ...


class RuleBasedLeadAnalyzer:
    """Fast local qualifier for obvious comments. It never makes network calls.

    In hybrid mode it returns None for ambiguous text so that OpenAI can be used only when
    explicitly enabled. The goal is to reserve model calls for the small part of traffic where
    language/context reasoning is actually useful.
    """

    _reaction_words: ClassVar[set[str]] = {
        "класс",
        "красиво",
        "красивая",
        "супер",
        "огонь",
        "вау",
        "зор",
        "zo'r",
        "zor",
        "chiroyli",
        "ajoyib",
        "cool",
        "nice",
        "муборак",
        "muborak",
        "buyursin",
        "буюрсин",
        "mashaalloh",
        "mashallah",
        "поздравляю",
        "nasib",
        "насиб",
    }

    def classify(self, context: LeadAnalysisContext) -> LeadAnalysis | None:
        raw = (context.comment or "").strip()
        text = self._norm(raw)
        caption = self._norm(context.post_caption or "")
        language = self._language(raw)

        if not raw:
            return self._result(False, 0, Intent.OTHER, None, language, "Пустой комментарий.")

        if self._is_reaction_only(raw, text):
            return self._result(
                False,
                5,
                Intent.REACTION,
                self._product(caption),
                language,
                "Это реакция на публикацию без явного намерения купить.",
            )

        if re.fullmatch(r"\+{1,3}", raw.replace(" ", "")):
            if self._caption_has_commercial_plus_cta(caption):
                score = min(99, 92 + self._history_boost(context))
                return self._result(
                    True,
                    score,
                    Intent.BUY,
                    self._product(caption),
                    language,
                    "Пользователь выполнил коммерческий призыв публикации и оставил «+» для получения цены, каталога или связи.",
                )
            return self._result(
                False,
                15,
                Intent.REACTION,
                self._product(caption),
                language,
                "Сам по себе «+» не доказывает покупательский интерес: в публикации не найден коммерческий призыв оставить плюс.",
            )

        checks: list[tuple[Intent, tuple[str, ...], int, str]] = [
            (
                Intent.BUY,
                (
                    "хочу купить",
                    "хочу заказать",
                    "заказать",
                    "купить",
                    "мне нужно",
                    "нужно ",
                    "buyurtma",
                    "buyurtma qil",
                    "olmoqchiman",
                    "olaman",
                    "olamiz",
                    "sotib ol",
                    "kerak",
                    "керак",
                ),
                94,
                "Пользователь прямо говорит о покупке или заказе.",
            ),
            (
                Intent.PRICE,
                (
                    "цена",
                    "сколько стоит",
                    "сколько",
                    "почем",
                    "почём",
                    "стоимость",
                    "narx",
                    "qancha",
                    "kancha",
                    "nech pul",
                    "necha pul",
                    "nechchi",
                    "нарх",
                    "қанча",
                    "канча",
                    "неч пул",
                    "неча пул",
                ),
                86,
                "Пользователь спрашивает цену товара.",
            ),
            (
                Intent.DELIVERY,
                (
                    "доставка",
                    "доставк",
                    "yetkaz",
                    "yetkazib berish",
                    "етказ",
                    "етказиб бериш",
                    "доставляете",
                    "доставите",
                ),
                82,
                "Пользователь уточняет доставку, что обычно относится к стадии выбора или заказа.",
            ),
            (
                Intent.AVAILABILITY,
                (
                    "в наличии",
                    "есть в наличии",
                    "есть?",
                    "есть ли",
                    "bormi",
                    "mavjud",
                    "qolganmi",
                    "борми",
                    "борми?",
                    "мавжуд",
                ),
                84,
                "Пользователь уточняет наличие товара.",
            ),
            (
                Intent.CATALOG,
                ("каталог", "catalog", "katalog", "варианты", "модели", "ассортимент"),
                78,
                "Пользователь запрашивает каталог или варианты товара.",
            ),
            (
                Intent.LOCATION,
                (
                    "адрес",
                    "где посмотреть",
                    "где вы",
                    "manzil",
                    "манзил",
                    "qayer",
                    "qayerda",
                    "каерда",
                    "қаерда",
                ),
                76,
                "Пользователь спрашивает, где посмотреть или купить товар.",
            ),
            (
                Intent.CONTACT,
                (
                    "номер",
                    "телефон",
                    "связаться",
                    "напишите",
                    "напишите мне",
                    "yozing",
                    "ёзинг",
                    "aloqa",
                    "алока",
                ),
                78,
                "Пользователь просит контакт или обратную связь.",
            ),
            (
                Intent.COLOR,
                ("цвет", "цвета", "rang", "ранг"),
                68,
                "Пользователь уточняет вариант цвета товара.",
            ),
            (
                Intent.SIZE,
                ("размер", "размеры", "o'lcham", "olcham", "ўлчам"),
                68,
                "Пользователь уточняет размер товара.",
            ),
        ]
        for intent, phrases, base_score, reason in checks:
            if any(phrase in text for phrase in phrases):
                score = min(99, base_score + self._history_boost(context))
                return self._result(
                    score >= 65,
                    score,
                    intent,
                    self._product(f"{caption} {text}"),
                    language,
                    reason,
                )

        if re.search(
            r"\b\d{1,3}\s*(шт|штук|dona|дона|та|персон|киши|kishi|kishilik|кишилик)\b",
            text,
        ):
            score = min(99, 90 + self._history_boost(context))
            return self._result(
                True,
                score,
                Intent.QUANTITY,
                self._product(f"{caption} {text}"),
                language,
                "Пользователь указывает конкретное количество, что является сильным коммерческим сигналом.",
            )

        if any(word in text for word in self._reaction_words) and len(text.split()) <= 16:
            return self._result(
                False,
                10,
                Intent.REACTION,
                self._product(caption),
                language,
                "Комментарий похож на похвалу или реакцию, а не на запрос о покупке.",
            )

        return None

    async def analyze(self, context: LeadAnalysisContext) -> LeadAnalysis:
        result = self.classify(context)
        if result is not None:
            return result
        return self._result(
            False,
            30,
            Intent.OTHER,
            self._product(context.post_caption),
            self._language(context.comment),
            "По локальным правилам покупательское намерение не определено уверенно.",
        )

    @staticmethod
    def _norm(value: str) -> str:
        return re.sub(r"\s+", " ", value.lower().replace("ё", "е")).strip()

    @staticmethod
    def _language(value: str) -> str:
        lowered = value.lower()
        uz_cyrillic_markers = ("нарх", "қанча", "канча", "борми", "керак", "етказ", "кишилик")
        if any(ch in lowered for ch in "ўқғҳ") or any(marker in lowered for marker in uz_cyrillic_markers):
            return "uz-cyrl"
        uz_markers = ("narx", "qancha", "kancha", "bormi", "kerak", "yetkaz", "kishilik")
        if any(marker in lowered for marker in uz_markers):
            return "uz"
        return "ru"

    @staticmethod
    def _is_reaction_only(raw: str, text: str) -> bool:
        if len(text) > 40:
            return False
        stripped = re.sub(r"[\W_]+", "", raw, flags=re.UNICODE)
        return stripped == "" and "+" not in raw

    @staticmethod
    def _caption_has_commercial_plus_cta(caption: str) -> bool:
        if "+" not in caption and "плюс" not in caption:
            return False
        commercial = (
            "цен",
            "стоим",
            "каталог",
            "заказ",
            "напиш",
            "остав",
            "комментар",
            "narx",
            "yoz",
            "buyurtma",
            "нарх",
            "ёз",
            "буюртма",
        )
        return any(marker in caption for marker in commercial)

    @staticmethod
    def _product(text: str) -> str | None:
        mapping = [
            (("обеден", "dining", "стол со стул", "комплект"), "DINING_SET"),
            (("ротанг", "rattan", "плетен"), "RATTAN_FURNITURE"),
            (("стул", "кресл", "chair"), "CHAIRS"),
            (("стол", "table"), "TABLE"),
            (("террас", "садов", "garden", "outdoor"), "OUTDOOR_FURNITURE"),
            (("кафе", "ресторан", "horeca"), "HORECA"),
        ]
        for markers, category in mapping:
            if any(marker in text for marker in markers):
                return category
        return None

    @staticmethod
    def _history_boost(context: LeadAnalysisContext) -> int:
        # Repeated interest matters, but interest across different sellers is even stronger:
        # it usually means the person is actively comparing the market rather than casually
        # reacting to one account. The cap prevents history from turning weak comments into HOT
        # leads by itself.
        repetition = min(9, len(context.previous_signals) * 3)
        other_sources = {
            item.competitor
            for item in context.previous_signals
            if item.competitor and item.competitor != context.competitor
        }
        comparison_boost = min(6, len(other_sources) * 3)
        return min(15, repetition + comparison_boost)

    @staticmethod
    def _result(
        is_lead: bool,
        score: int,
        intent: Intent,
        product: str | None,
        language: str,
        reason: str,
    ) -> LeadAnalysis:
        return LeadAnalysis(
            is_lead=is_lead,
            lead_score=score,
            intent=intent,
            product_category=product,
            language=language,
            reason=reason,
        )


class OpenAILeadAnalyzer:
    def __init__(self, api_key: str, model: str, client: Any | None = None) -> None:
        self.model = model
        if client is not None:
            self.client = client
        else:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise AIAnalysisError("OpenAI SDK is not installed") from exc
            self.client = AsyncOpenAI(api_key=api_key)

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
            "product relevance, specificity, prior signals, and known_customer_context that was "
            "explicitly entered by a sales manager. Treat manager-entered context as useful CRM "
            "history, but do not invent missing facts. A '+' is commercial only "
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


class BudgetedCachedOpenAIAnalyzer:
    def __init__(
        self,
        inner: OpenAILeadAnalyzer,
        session_factory: async_sessionmaker[AsyncSession],
        usage: ExternalUsageService,
        *,
        enabled: bool,
        daily_limit: int,
    ) -> None:
        self.inner = inner
        self.session_factory = session_factory
        self.usage = usage
        self.enabled = enabled
        self.daily_limit = daily_limit

    async def analyze(self, context: LeadAnalysisContext) -> LeadAnalysis:
        cache_key = self._cache_key(context)
        async with self.session_factory() as session:
            cached = await session.scalar(
                select(AnalysisCache).where(AnalysisCache.cache_key == cache_key)
            )
            if cached is not None:
                cached.hit_count += 1
                cached.last_used_at = datetime.now(UTC)
                await session.commit()
                return LeadAnalysis.model_validate(cached.result_json)

        if not self.enabled:
            raise AIAnalysisError(
                "OpenAI отключён для экономии токенов. Неоднозначный сигнал оставлен в очереди AI."
            )
        try:
            await self.usage.assert_available("openai", self.daily_limit)
        except ExternalBudgetExceeded as exc:
            raise AIAnalysisError(str(exc)) from exc

        try:
            analysis = await self.inner.analyze(context)
        except Exception:
            await self.usage.record("openai", "lead_analysis", success=False)
            raise
        await self.usage.record("openai", "lead_analysis", success=True)

        async with self.session_factory() as session:
            existing = await session.scalar(
                select(AnalysisCache).where(AnalysisCache.cache_key == cache_key)
            )
            if existing is None:
                session.add(
                    AnalysisCache(
                        cache_key=cache_key,
                        model=self.inner.model,
                        result_json=analysis.model_dump(mode="json"),
                    )
                )
                await session.commit()
        return analysis

    def _cache_key(self, context: LeadAnalysisContext) -> str:
        normalized = {
            "model": self.inner.model,
            "competitor": context.competitor,
            "post_caption": context.post_caption,
            "comment": context.comment,
            "previous_signals": [asdict(item) for item in context.previous_signals],
            "previous_interests": context.previous_interests,
            "known_customer_context": context.known_customer_context,
        }
        raw = json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class HybridLeadAnalyzer:
    def __init__(
        self,
        rules: RuleBasedLeadAnalyzer,
        openai: LeadAnalyzer | None,
        *,
        mode: str = "hybrid",
    ) -> None:
        self.rules = rules
        self.openai = openai
        self.mode = mode

    async def analyze_with_source(
        self, context: LeadAnalysisContext
    ) -> tuple[LeadAnalysis, str]:
        if self.mode in {"rules", "hybrid"}:
            local = self.rules.classify(context)
            if local is not None:
                return local, "local_rules"
            if self.mode == "rules":
                return await self.rules.analyze(context), "local_rules"
        if self.openai is None:
            raise AIAnalysisError("OpenAI не настроен для неоднозначного сигнала")
        return await self.openai.analyze(context), "openai_or_cache"

    async def analyze(self, context: LeadAnalysisContext) -> LeadAnalysis:
        analysis, _source = await self.analyze_with_source(context)
        return analysis


class UnavailableLeadAnalyzer:
    async def analyze(self, context: LeadAnalysisContext) -> LeadAnalysis:
        raise AIAnalysisError("AI analyzer is not configured")
