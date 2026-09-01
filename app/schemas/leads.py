from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Intent(StrEnum):
    BUY = "BUY"
    PRICE = "PRICE"
    AVAILABILITY = "AVAILABILITY"
    DELIVERY = "DELIVERY"
    QUANTITY = "QUANTITY"
    COLOR = "COLOR"
    SIZE = "SIZE"
    LOCATION = "LOCATION"
    CATALOG = "CATALOG"
    CONTACT = "CONTACT"
    QUESTION = "QUESTION"
    REACTION = "REACTION"
    SPAM = "SPAM"
    OTHER = "OTHER"


class FunnelStage(StrEnum):
    NON_COMMERCIAL = "NON_COMMERCIAL"
    AWARENESS = "AWARENESS"
    CONSIDERATION = "CONSIDERATION"
    PURCHASE_INTENT = "PURCHASE_INTENT"
    READY_TO_BUY = "READY_TO_BUY"


class Urgency(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PurchaseHorizon(StrEnum):
    TODAY = "TODAY"
    THIS_WEEK = "THIS_WEEK"
    THIS_MONTH = "THIS_MONTH"
    RESEARCHING = "RESEARCHING"
    UNKNOWN = "UNKNOWN"


class BuyerRole(StrEnum):
    B2C_CONSUMER = "B2C_CONSUMER"
    B2B_HORECA = "B2B_HORECA"
    DESIGNER_CONTRACTOR = "DESIGNER_CONTRACTOR"
    JOB_SEEKER = "JOB_SEEKER"
    UNKNOWN = "UNKNOWN"


class CommercialSignalQuality(StrEnum):
    NON_COMMERCIAL = "NON_COMMERCIAL"
    WEAK_COMMERCIAL = "WEAK_COMMERCIAL"
    MEDIUM_COMMERCIAL = "MEDIUM_COMMERCIAL"
    STRONG_COMMERCIAL = "STRONG_COMMERCIAL"


class LeadScoreFactors(BaseModel):
    """Закрытая схема факторов: OpenAI strict JSON запрещает свободный dict."""

    model_config = ConfigDict(extra="forbid")

    intent_strength: int = Field(default=0, ge=0)
    intent_score: int = Field(default=0, ge=0)
    activity_score: int = Field(default=0, ge=0)
    specificity_score: int = Field(default=0, ge=0)
    value_score: int = Field(default=0, ge=0)
    fit_score: int = Field(default=0, ge=0)
    source_quality_score: int = Field(default=0, ge=0)
    confidence_score: int = Field(default=0, ge=0)
    priority_score: int = Field(default=0, ge=0)
    role_score: int = Field(default=0, ge=0)
    history_boost: int = Field(default=0, ge=0)
    sequence_score: int = Field(default=0, ge=0)
    validated_commercial_count: int = Field(default=0, ge=0)
    validated_competitor_count: int = Field(default=0, ge=0)
    objection_penalty: int = Field(default=0, ge=0)

    def __getitem__(self, key: str) -> int:
        return int(getattr(self, key))

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and hasattr(self, key)

    def get(self, key: str, default: int = 0) -> int:
        return int(getattr(self, key, default))


class LeadAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_lead: bool
    lead_score: int = Field(ge=0, le=100)
    intent: Intent
    product_category: str | None
    language: str
    reason: str
    confidence: int = Field(default=50, ge=0, le=100)
    funnel_stage: FunnelStage = FunnelStage.AWARENESS
    urgency: Urgency = Urgency.LOW
    purchase_horizon: PurchaseHorizon = PurchaseHorizon.UNKNOWN
    evidence: list[str] = Field(default_factory=list, max_length=6)
    risk_flags: list[str] = Field(default_factory=list, max_length=6)
    recommended_action: str = "Проверить контекст и решить, требуется ли ответ менеджера."
    intelligence_version: str = "2.0"
    buyer_role: BuyerRole = BuyerRole.UNKNOWN
    factors: LeadScoreFactors = Field(default_factory=LeadScoreFactors)
    evidence_ids: list[int] = Field(default_factory=list)
    contradiction_ids: list[int] = Field(default_factory=list)
    is_commercial: bool = False
    commercial_quality: CommercialSignalQuality = (
        CommercialSignalQuality.NON_COMMERCIAL
    )
    commercial_stage: FunnelStage = FunnelStage.NON_COMMERCIAL
    intent_score: int = Field(default=0, ge=0, le=100)
    activity_score: int = Field(default=0, ge=0, le=100)
    specificity_score: int = Field(default=0, ge=0, le=100)
    value_score: int = Field(default=0, ge=0, le=100)
    fit_score: int = Field(default=0, ge=0, le=100)
    source_quality_score: int = Field(default=0, ge=0, le=100)
    confidence_score: int = Field(default=0, ge=0, le=100)
    priority_score: int = Field(default=0, ge=0, le=100)
    quantity: int | None = Field(default=None, ge=1)
    next_best_action: str = "Проверить контекст и выбрать следующее действие."
    short_reason: str = ""
