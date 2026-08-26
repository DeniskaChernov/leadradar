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
