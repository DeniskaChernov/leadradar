from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Protocol
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AIRequest, AIRequestStatus
from app.schemas.leads import (
    BuyerRole,
    FunnelStage,
    Intent,
    LeadAnalysis,
    PurchaseHorizon,
    Urgency,
)
from app.services.usage_service import ExternalUsageService

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
    evidence_ids: list[int] = field(default_factory=list)
    public_signal_id: int | None = None
    lead_id: int | None = None


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
            return self._result(
                False, 0, Intent.OTHER, None, language, "Пустой комментарий.", context
            )

        if self._is_reaction_only(raw, text):
            return self._result(
                False,
                5,
                Intent.REACTION,
                self._product(caption),
                language,
                "Это реакция на публикацию без явного намерения купить.",
                context,
            )

        non_commercial = (
            "сколько лет",
            "сколько красоты",
            "ish kerak",
            "работа нужна",
            "вакансия",
            "резюме",
        )
        if any(marker in text for marker in non_commercial):
            return self._result(
                False,
                5,
                Intent.SPAM,
                self._product(caption),
                language,
                "Комментарий не относится к покупке мебели.",
                context,
            )

        negative_purchase = (
            "не хочу",
            "не нужно",
            "не буду покупать",
            "покупать не буду",
            "kerak emas",
            "olmayman",
            "сотиб олмайман",
        )
        if any(marker in text for marker in negative_purchase):
            return self._result(
                False,
                12,
                Intent.OTHER,
                self._product(f"{caption} {text}"),
                language,
                "Пользователь явно отрицает намерение покупать.",
                context,
                risk_flags=["Явный отказ от покупки"],
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
                    context,
                )
            return self._result(
                False,
                15,
                Intent.REACTION,
                self._product(caption),
                language,
                "Сам по себе «+» не доказывает покупательский интерес: в публикации не найден коммерческий призыв оставить плюс.",
                context,
                risk_flags=["Смысл «+» зависит от призыва в публикации"],
            )

        designer_markers = (
            "дизайн-проект",
            "дизайнер",
            "дизайн проект",
            "3d модель",
            "3д модель",
            "3d model",
            "dizayner",
            "dizayn loyiha",
            "proyekt uchun",
            "для проекта",
        )
        if any(marker in text for marker in designer_markers):
            score = min(99, 88 + self._history_boost(context))
            return self._result(
                True,
                score,
                Intent.BUY,
                self._product(f"{caption} {text}") or "DESIGN_PROJECT",
                language,
                "Запрос от дизайнера или под дизайн-проект/комплектацию объекта.",
                context,
                buyer_role=BuyerRole.DESIGNER_CONTRACTOR,
                role_score=85,
            )

        business_markers = (
            "для кафе",
            "для ресторана",
            "для гостиницы",
            "для объекта",
            "для отеля",
            "оптом",
            "ulgurji",
            "kafe uchun",
            "restoran uchun",
            "mehmonxona uchun",
            "choyxona",
        )
        if any(marker in text for marker in business_markers):
            score = min(99, 90 + self._history_boost(context))
            return self._result(
                True,
                score,
                Intent.BUY,
                self._product(f"{caption} {text}") or "HORECA",
                language,
                "Пользователь описывает коммерческое или оптовое применение мебели (HoReCa / B2B).",
                context,
                buyer_role=BuyerRole.B2B_HORECA,
                role_score=90,
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
                    "мне нужен",
                    "мне нужна",
                    "можно заказать",
                    "хотела бы заказать",
                    "хотел бы заказать",
                    "нужно ",
                    "buyurtma",
                    "buyurtma qil",
                    "olmoqchiman",
                    "olaman",
                    "olamiz",
                    "olsa bo'ladimi",
                    "olsa boladimi",
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
                    "сколько будет",
                    "какая цена",
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
                    "рассрочка",
                    "в рассрочку",
                    "nasiya",
                    "bo'lib to'lash",
                    "bolib tolash",
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
                Intent.COLOR,
                ("цвет", "цвета", "цвете", "rang", "ранг"),
                74,
                "Пользователь уточняет вариант цвета товара.",
            ),
            (
                Intent.SIZE,
                ("размер", "размеры", "o'lcham", "olcham", "ўлчам"),
                74,
                "Пользователь уточняет размер товара.",
            ),
            (
                Intent.AVAILABILITY,
                (
                    "в наличии",
                    "есть в наличии",
                    "есть?",
                    "есть ли",
                    "у вас есть",
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
        ]
        matched_checks: list[tuple[Intent, int, str, list[str]]] = []
        for intent, phrases, base_score, reason in checks:
            matched_phrases = [phrase for phrase in phrases if phrase in text]
            if matched_phrases:
                matched_checks.append((intent, base_score, reason, matched_phrases[:2]))
        if matched_checks:
            # The checks are ordered from the most decision-specific intent to more generic
            # signals. Preserve that semantic priority: e.g. "delivery bormi" contains the
            # generic availability word too, but the real question is about delivery.
            intent, base_score, reason, _phrases = matched_checks[0]
            specificity_boost = min(6, (len(matched_checks) - 1) * 3)
            score = min(99, base_score + specificity_boost + self._history_boost(context))
            evidence = [reason]
            evidence.extend(
                f"Дополнительный сигнал: {extra_reason}"
                for extra_intent, _score, extra_reason, _matched in matched_checks
                if extra_intent != intent
            )
            return self._result(
                score >= 65,
                score,
                intent,
                self._product(f"{caption} {text}"),
                language,
                reason,
                context,
                evidence=evidence[:4],
            )

        if re.search(
            r"\b\d{1,3}\s*(шт\w*|штук\w*|dona\w*|дона\w*|та|персон\w*|киши\w*|kishi\w*|комплект\w*|стул\w*|стол\w*|кресл\w*|диван\w*)\b",
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
                context,
            )

        objection_markers = ("дорого", "слишком дорого", "qimmat", "киммат", "қиммат")
        if any(marker in text for marker in objection_markers):
            score = min(79, 58 + self._history_boost(context))
            return self._result(
                score >= 65,
                score,
                Intent.PRICE,
                self._product(f"{caption} {text}"),
                language,
                "Пользователь выражает ценовое возражение: интерес возможен, но требуется уточнение бюджета.",
                context,
                risk_flags=["Ценовое возражение"],
            )

        if any(word in text for word in self._reaction_words) and len(text.split()) <= 16:
            return self._result(
                False,
                10,
                Intent.REACTION,
                self._product(caption),
                language,
                "Комментарий похож на похвалу или реакцию, а не на запрос о покупке.",
                context,
                buyer_role=BuyerRole.UNKNOWN,
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
            context,
            risk_flags=["Недостаточно явных коммерческих признаков"],
            buyer_role=BuyerRole.UNKNOWN,
        )

    @staticmethod
    def _norm(value: str) -> str:
        return re.sub(r"\s+", " ", value.lower().replace("ё", "е")).strip()

    @staticmethod
    def _language(value: str) -> str:
        lowered = value.lower()
        uz_cyrillic_markers = ("нарх", "қанча", "канча", "борми", "керак", "етказ", "кишилик")
        if any(ch in lowered for ch in "ўқғҳ") or any(
            marker in lowered for marker in uz_cyrillic_markers
        ):
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
        """Map raw text to a product taxonomy category.

        Ordered from most-specific to most-generic so that compound signals
        (e.g. "ротанговый диван для ресторана") hit the right bucket first.
        """
        lowered = (text or "").lower()
        mapping = [
            # Specific compound sets — highest priority
            (("обеден", "dining", "стол со стул", "комплект стол", "komplekt stol"), "DINING_SET"),
            # Rattan sub-types — before generic rattan
            (
                (
                    "диван ротанг",
                    "диваны ротанг",
                    "диваны из ротанга",
                    "ротанг диван",
                    "ротанговый диван",
                    "плетен диван",
                    "диван плетен",
                    "rattan sofa",
                    "rattan divan",
                ),
                "RATTAN_SOFA",
            ),
            (
                (
                    "кресло ротанг",
                    "ротанг кресл",
                    "плетен кресл",
                    "плетеное кресло",
                    "плетеные кресла",
                    "rattan armchair",
                    "rattan kreslo",
                ),
                "RATTAN_ARMCHAIR",
            ),
            (
                (
                    "гарнитур ротанг",
                    "ротанг набор",
                    "комплект ротанг",
                    "rattan garden set",
                    "rattan komplekt",
                ),
                "RATTAN_GARDEN_SET",
            ),
            (
                (
                    "барный стул",
                    "барные стулья",
                    "bar stool",
                    "высокий стул",
                    "баркаунтер",
                    "bar stol",
                ),
                "RATTAN_BAR_STOOL",
            ),
            (("качел", "swing", "хорч"), "SWING"),
            (("пергол", "pergola", "беседк"), "PERGOLA"),
            # Generic rattan — catch-all for unspecified rattan
            (("ротанг", "rattan", "плетен"), "RATTAN_FURNITURE"),
            # Standard categories
            (("стул", "кресл", "chair"), "CHAIRS"),
            (("стол", "table"), "TABLE"),
            (("террас", "садов", "garden", "outdoor", "уличн"), "OUTDOOR_FURNITURE"),
            (("кафе", "ресторан", "horeca"), "HORECA"),
        ]
        for markers, category in mapping:
            if any(marker in lowered for marker in markers):
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
    def _detect_buyer_role(
        text: str,
        caption: str,
        is_lead: bool,
        intent: Intent,
        reason: str,
        product: str | None,
    ) -> BuyerRole:
        if re.search(r"\b(ish\s+kerak|работа\s+нужна|ваканси\w*|резюме|ish\s+bormi\w*)\b", text):
            return BuyerRole.JOB_SEEKER

        designer_markers = (
            "дизайн-проект",
            "дизайнер",
            "дизайн проект",
            "3d модель",
            "3д модель",
            "3d model",
            "dizayner",
            "dizayn loyiha",
            "proyekt uchun",
            "для проекта",
        )
        if any(marker in text for marker in designer_markers):
            return BuyerRole.DESIGNER_CONTRACTOR

        business_markers = (
            "для кафе",
            "для ресторана",
            "для гостиницы",
            "для объекта",
            "для отеля",
            "оптом",
            "ulgurji",
            "kafe uchun",
            "restoran uchun",
            "mehmonxona uchun",
            "choyxona",
        )
        quantity_match = re.search(
            r"\b(\d{1,3})\s*(шт\w*|штук\w*|dona\w*|дона\w*|та|персон\w*|киши\w*|kishi\w*|комплект\w*|стул\w*|стол\w*|кресл\w*|диван\w*|chair\w*|table\w*)\b",
            text,
        )
        qty = int(quantity_match.group(1)) if quantity_match else 0
        if any(marker in text for marker in business_markers) or qty >= 10 or product == "HORECA":
            return BuyerRole.B2B_HORECA

        if is_lead:
            return BuyerRole.B2C_CONSUMER
        return BuyerRole.UNKNOWN

    @staticmethod
    def _result(
        is_lead: bool,
        score: int,
        intent: Intent,
        product: str | None,
        language: str,
        reason: str,
        context: LeadAnalysisContext | None = None,
        *,
        evidence: list[str] | None = None,
        risk_flags: list[str] | None = None,
        buyer_role: BuyerRole | None = None,
        intent_strength: int | None = None,
        specificity_score: int | None = None,
        role_score: int | None = None,
        objection_penalty: int = 0,
    ) -> LeadAnalysis:
        raw = RuleBasedLeadAnalyzer._norm(context.comment) if context else ""
        caption = RuleBasedLeadAnalyzer._norm(context.post_caption) if context else ""
        urgent_markers = (
            "срочно",
            "сегодня",
            "прямо сейчас",
            "bugun",
            "hozir",
            "tezda",
            "бугун",
            "хозир",
        )
        week_markers = ("на этой неделе", "this week", "shu hafta", "шу хафта")
        month_markers = ("в этом месяце", "this month", "shu oy", "шу ой")
        has_urgency = any(marker in raw for marker in urgent_markers)
        if has_urgency:
            urgency = Urgency.HIGH
            horizon = PurchaseHorizon.TODAY
        elif any(marker in raw for marker in week_markers):
            urgency = Urgency.MEDIUM
            horizon = PurchaseHorizon.THIS_WEEK
        elif any(marker in raw for marker in month_markers):
            urgency = Urgency.MEDIUM
            horizon = PurchaseHorizon.THIS_MONTH
        elif intent in {Intent.PRICE, Intent.CATALOG, Intent.COLOR, Intent.SIZE}:
            urgency = Urgency.MEDIUM if is_lead else Urgency.LOW
            horizon = PurchaseHorizon.RESEARCHING
        else:
            urgency = Urgency.MEDIUM if is_lead else Urgency.LOW
            horizon = PurchaseHorizon.UNKNOWN

        if not is_lead:
            stage = FunnelStage.NON_COMMERCIAL
        elif intent in {Intent.BUY, Intent.QUANTITY} and score >= 88:
            stage = FunnelStage.READY_TO_BUY
        elif intent in {Intent.BUY, Intent.QUANTITY, Intent.CONTACT}:
            stage = FunnelStage.PURCHASE_INTENT
        else:
            stage = FunnelStage.CONSIDERATION

        confidence = min(98, max(35, abs(score - 50) + 48))
        if intent == Intent.OTHER:
            confidence = min(confidence, 52)
        details = list(evidence or [reason])
        if context and context.previous_signals:
            details.append(f"Ранее найдено сигналов этого клиента: {len(context.previous_signals)}")
        if product:
            details.append(f"Товарный контекст: {product}")

        # Determine BuyerRole
        if buyer_role is None:
            buyer_role = RuleBasedLeadAnalyzer._detect_buyer_role(
                text=raw,
                caption=caption,
                is_lead=is_lead,
                intent=intent,
                reason=reason,
                product=product,
            )

        # Determine role_score
        if role_score is None:
            if buyer_role == BuyerRole.B2B_HORECA:
                role_score = 90
            elif buyer_role == BuyerRole.DESIGNER_CONTRACTOR:
                role_score = 85
            elif buyer_role == BuyerRole.B2C_CONSUMER:
                role_score = 70
            elif buyer_role == BuyerRole.JOB_SEEKER:
                role_score = 5
            else:
                role_score = 20

        # Determine intent_strength
        if intent_strength is None:
            intent_strength = score

        # Determine specificity_score
        if specificity_score is None:
            spec = 0
            if product:
                spec += 5
            if context and any(ch.isdigit() for ch in (context.comment or "")):
                spec += 5
            specificity_score = min(10, spec)

        history_boost = RuleBasedLeadAnalyzer._history_boost(context) if context else 0

        factors = {
            "intent_strength": intent_strength,
            "specificity_score": specificity_score,
            "role_score": role_score,
            "history_boost": history_boost,
            "objection_penalty": objection_penalty,
        }

        evidence_ids = list(context.evidence_ids) if context and context.evidence_ids else []

        actions = {
            Intent.BUY: "Связаться в течение 10 минут, подтвердить модель, количество и удобный способ оформления.",
            Intent.QUANTITY: "Уточнить точное количество, сроки и подготовить расчёт с оптовыми условиями.",
            Intent.PRICE: "Ответить ценой и сразу уточнить бюджет, количество и предпочтительную модель.",
            Intent.AVAILABILITY: "Подтвердить наличие и предложить забронировать подходящий комплект.",
            Intent.DELIVERY: "Уточнить город и срок, затем дать точную стоимость и условия доставки.",
            Intent.CATALOG: "Отправить короткую подборку из 3–5 релевантных моделей и задать вопрос о бюджете.",
            Intent.LOCATION: "Отправить адрес шоурума, часы работы и предложить удобное время визита.",
            Intent.CONTACT: "Назначить менеджера и ответить в том же канале без задержки.",
            Intent.COLOR: "Уточнить нужный оттенок и отправить доступные варианты с фото.",
            Intent.SIZE: "Запросить требуемые размеры и проверить подходящие модели.",
        }
        recommended_action = actions.get(
            intent,
            "Не отправлять менеджеру; сохранить сигнал как контекст для будущего интереса."
            if not is_lead
            else "Менеджеру проверить контекст и задать один уточняющий вопрос.",
        )
        return LeadAnalysis(
            is_lead=is_lead,
            lead_score=score,
            intent=intent,
            product_category=product,
            language=language,
            reason=reason,
            confidence=confidence,
            funnel_stage=stage,
            urgency=urgency,
            purchase_horizon=horizon,
            evidence=details[:6],
            risk_flags=(risk_flags or [])[:6],
            recommended_action=recommended_action,
            intelligence_version="2.0",
            buyer_role=buyer_role,
            factors=factors,
            evidence_ids=evidence_ids,
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
            "business_goal": (
                "Find people with credible furniture purchase intent and give a manager the "
                "single best next action without turning social engagement into false leads."
            ),
        }
        system_prompt = (
            "You are the lead-intelligence layer for a furniture seller (version 2.0). Qualify public Instagram "
            "comments in Russian, Uzbek Latin, Uzbek Cyrillic, or mixed language. The outcome must "
            "help a sales manager decide whether to act, why, how quickly, and what to say next. "
            "Use only supplied evidence. Never infer private traits, contact details, income, or "
            "facts that are not present. Evaluate the comment together with the Reel caption and "
            "CTA, product fit, request specificity, repetition across prior signals, comparison "
            "across competitors, buyer role (B2C, HoReCa/B2B, Designer), and manager-entered CRM context. A plus sign is commercial only "
            "when the Reel explicitly asks for it to receive a price, catalog, or contact. Praise, "
            "emoji, congratulations, job requests, and unrelated conversation are not leads. "
            "Negation overrides keyword matches. Distinguish active purchase intent from research, "
            "price objections, and ambiguous questions. Score 0–100 consistently; confidence means "
            "confidence in the classification, not purchase probability. Provide short observable "
            "evidence, uncertainty flags, intelligence_version '2.0', buyer_role, factors breakdown, "
            "evidence_ids, and one concrete manager action. Do not reveal hidden "
            "chain-of-thought or invent a rationale. Return only the validated structured result."
        )
        try:
            response = await self.client.responses.parse(
                model=self.model,
                instructions=system_prompt,
                input=json.dumps(payload, ensure_ascii=False, default=str),
                text_format=LeadAnalysis,
                reasoning={"effort": "medium"},
                max_output_tokens=900,
                store=False,
                prompt_cache_key="lead-radar-qualifier-v2",
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
    ANALYSIS_VERSION = 3

    def __init__(
        self,
        inner: OpenAILeadAnalyzer,
        session_factory: async_sessionmaker[AsyncSession],
        usage: ExternalUsageService,
        *,
        enabled: bool,
        daily_limit: int,
        worker_id: str = "default-worker",
    ) -> None:
        self.inner = inner
        self.session_factory = session_factory
        self.usage = usage
        self.enabled = enabled
        self.daily_limit = daily_limit
        self.worker_id = worker_id if worker_id != "default-worker" else f"ai-{uuid4().hex[:12]}"

    def context_fingerprint(self, context: LeadAnalysisContext) -> str:
        """Calculates canonical SHA-256 context fingerprint factoring all parameters."""
        canonical_dict = {
            "analysis_contract_version": self.ANALYSIS_VERSION,
            "model": self.inner.model,
            "competitor": (context.competitor or "").strip().lower(),
            "post_caption": (context.post_caption or "").strip(),
            "comment": (context.comment or "").strip(),
            "username": (context.username or "").strip().lower(),
            "previous_signals": [
                {
                    "competitor": (s.competitor or "").strip().lower(),
                    "comment": (s.comment or "").strip(),
                    "discovered_at": s.discovered_at,
                }
                for s in sorted(context.previous_signals, key=lambda x: x.discovered_at)
            ],
            "previous_interests": sorted(context.previous_interests),
            "known_customer_context": dict(sorted(context.known_customer_context.items())),
            "evidence_ids": sorted(context.evidence_ids),
        }
        raw = json.dumps(canonical_dict, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def analyze(self, context: LeadAnalysisContext) -> LeadAnalysis:
        fingerprint = self.context_fingerprint(context)
        now = datetime.now(UTC)
        if context.lead_id is None:
            raise AIAnalysisError("AI request requires a persisted lead_id")

        cached, request_id, claim_token = await self._claim_request(
            context.lead_id, fingerprint, now
        )
        if cached is not None:
            return cached
        if request_id is None or claim_token is None:
            raise AIAnalysisError(
                "AI анализ для данного контекста уже выполняется другим процессом."
            )

        if not self.enabled:
            await self._release_request_claim(
                request_id,
                claim_token,
                AIRequestStatus.RETRYABLE,
                "OpenAI disabled",
            )
            raise AIAnalysisError(
                "OpenAI отключён для экономии токенов. Неоднозначный сигнал оставлен в очереди AI."
            )

        try:
            reservation_id = await self.usage.reserve_budget(
                "openai",
                "lead_analysis",
                self.daily_limit,
                units=1,
                request_fingerprint=fingerprint,
                lease_seconds=120,
            )
        except Exception as exc:
            await self._release_request_claim(
                request_id, claim_token, AIRequestStatus.RETRYABLE, str(exc)
            )
            raise

        try:
            analysis = await self.inner.analyze(context)
        except Exception as exc:
            await self.usage.release_reservation(reservation_id)
            await self._release_request_claim(
                request_id, claim_token, AIRequestStatus.FAILED, str(exc)
            )
            raise

        async with self.session_factory() as session:
            saved = (
                await session.execute(
                    update(AIRequest)
                    .where(
                        AIRequest.id == request_id,
                        AIRequest.status == AIRequestStatus.CLAIMED,
                        AIRequest.claim_token == claim_token,
                    )
                    .values(
                        status=AIRequestStatus.SUCCEEDED,
                        result_json=analysis.model_dump(mode="json"),
                        error=None,
                        claim_expires_at=None,
                        claim_token=None,
                        worker_id=None,
                    )
                    .returning(AIRequest.id)
                )
            ).scalar_one_or_none()
            await session.commit()
        if saved is None:
            await self.usage.release_reservation(reservation_id)
            raise AIAnalysisError("AI result lost its durable claim before persistence")

        await self.usage.finalize_reservation(
            reservation_id,
            units=1,
            success=True,
            details={"model": self.inner.model, "fingerprint": fingerprint},
        )

        return analysis

    async def _claim_request(
        self, lead_id: int, fingerprint: str, now: datetime
    ) -> tuple[LeadAnalysis | None, int | None, str | None]:
        token = uuid4().hex
        async with self.session_factory() as session:
            request = AIRequest(
                lead_id=lead_id,
                analysis_version=self.ANALYSIS_VERSION,
                context_fingerprint=fingerprint,
                model=self.inner.model,
                status=AIRequestStatus.CLAIMED,
                claimed_at=now,
                claim_expires_at=now + timedelta(seconds=120),
                worker_id=self.worker_id,
                claim_token=token,
                attempt_count=1,
            )
            session.add(request)
            try:
                await session.commit()
                return None, request.id, token
            except IntegrityError:
                await session.rollback()

        async with self.session_factory() as session:
            existing = await session.scalar(
                select(AIRequest).where(
                    AIRequest.lead_id == lead_id,
                    AIRequest.analysis_version == self.ANALYSIS_VERSION,
                    AIRequest.context_fingerprint == fingerprint,
                )
            )
            if existing is None:
                return None, None, None
            if existing.status == AIRequestStatus.SUCCEEDED and existing.result_json:
                return LeadAnalysis.model_validate(existing.result_json), None, None
            claimed_id = (
                await session.execute(
                    update(AIRequest)
                    .where(
                        AIRequest.id == existing.id,
                        or_(
                            AIRequest.status != AIRequestStatus.CLAIMED,
                            AIRequest.claim_expires_at.is_(None),
                            AIRequest.claim_expires_at <= now,
                        ),
                    )
                    .values(
                        status=AIRequestStatus.CLAIMED,
                        claimed_at=now,
                        claim_expires_at=now + timedelta(seconds=120),
                        worker_id=self.worker_id,
                        claim_token=token,
                        attempt_count=AIRequest.attempt_count + 1,
                        error=None,
                    )
                    .execution_options(synchronize_session=False)
                    .returning(AIRequest.id)
                )
            ).scalar_one_or_none()
            await session.commit()
        return None, claimed_id, token if claimed_id is not None else None

    async def _release_request_claim(
        self,
        request_id: int,
        claim_token: str,
        status: AIRequestStatus,
        error: str,
    ) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(AIRequest)
                .where(
                    AIRequest.id == request_id,
                    AIRequest.status == AIRequestStatus.CLAIMED,
                    AIRequest.claim_token == claim_token,
                )
                .values(
                    status=status,
                    error=error[:1000],
                    claim_expires_at=None,
                    claim_token=None,
                    worker_id=None,
                )
            )
            await session.commit()


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

    async def analyze_with_source(self, context: LeadAnalysisContext) -> tuple[LeadAnalysis, str]:
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
