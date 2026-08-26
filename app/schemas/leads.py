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


class LeadAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_lead: bool
    lead_score: int = Field(ge=0, le=100)
    intent: Intent
    product_category: str | None
    language: str
    reason: str

