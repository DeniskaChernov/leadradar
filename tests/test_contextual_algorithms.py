from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.schemas.leads import CommercialSignalQuality, Intent
from app.services.ai_service import (
    LeadAnalysisContext,
    RuleBasedLeadAnalyzer,
    ValidatedPreviousSignal,
)
from app.services.assortment_policy import assess_assortment
from app.services.b2b_policy import B2BPolicy
from app.services.lead_scoring_v3 import HistoricalSignal, LeadScorerV3, parse_observed_at
from app.services.product_context_service import resolve_product_context


def context(text, caption="Плетёная мебель", parent=""):
    return LeadAnalysisContext(competitor="public_furniture", post_caption=caption, comment=text,
                               username="public_buyer", previous_signals=[], previous_interests=[],
                               parent_comment=parent, source_vertical="FURNITURE")


@pytest.mark.parametrize("text,caption,categories", [
    ("Плетёные кресла и пластиковые стулья цена?", "", ("RATTAN_ARMCHAIR", "PLASTIC_CHAIRS")),
    ("Plastic chairs and rattan armchairs", "", ("PLASTIC_CHAIRS", "RATTAN_ARMCHAIR")),
    ("Кресло цена?", "Ротанговый диван и обычное мягкое кресло", ("ARMCHAIR",)),
    ("Кресло цена?", "Диван из ротанга и кресло", ("ARMCHAIR",)),
    ("Кресло цена?", "Плетёные кресла и обычное мягкое кресло", ("ARMCHAIR",)),
    ("Кресло цена?", "Пластиковые стулья", ("ARMCHAIR",)),
    ("Стул цена?", "Пластиковые стулья и плетёные стулья", ("CHAIRS",)),
    ("Стул цена?", "Пластиковые стулья и обычные стулья", ("CHAIRS",)),
    ("Стул цена?", "Пластиковые стулья и плетёные кресла", ("PLASTIC_CHAIRS",)),
    ("Обычное мягкое кресло цена?", "Плетёное кресло", ("ARMCHAIR",)),
    ("Плетёное кресло и стол нужны", "", ("RATTAN_ARMCHAIR", "RATTAN_TABLE")),
])
def test_materials_belong_to_the_requested_product(text, caption, categories):
    result = resolve_product_context(text, caption)
    assert result.categories == categories
    if categories == ("ARMCHAIR",):
        assert assess_assortment(text, caption).status == "REVIEW"


@pytest.mark.parametrize("text,category", [
    ("Офисное кресло не нужно, хочу пластиковые стулья", "PLASTIC_CHAIRS"),
    ("Диван не нужен, хочу плетёное кресло", "RATTAN_ARMCHAIR"),
    ("Комод не нужен, нужны обеденные стулья", "DINING_CHAIRS"),
    ("Divan kerak emas, ratan stul kerak", "RATTAN_CHAIR"),
])
def test_declining_one_product_does_not_reject_the_explicit_order_of_another(text, category):
    product = resolve_product_context(text, "Мебель")
    assert product.category == category and product.negated_categories
    result = RuleBasedLeadAnalyzer().classify(context(text, "Мебель"))
    assert result and result.is_lead and result.intent == Intent.BUY
    assert result.product_category == category


@pytest.mark.parametrize("text", ["Плетёные кресла не нужны", "Не хочу покупать стулья", "Ratan stul kerak emas"])
def test_complete_purchase_refusal_stays_rejected(text):
    result = RuleBasedLeadAnalyzer().classify(context(text))
    assert result and not result.is_lead
    assert result.product_category is None


@pytest.mark.parametrize("text", ["+", "++", "++++", "+ 🙏", "+👏"])
def test_explicit_commercial_plus_is_a_warm_request_not_a_hot_order(text):
    result = RuleBasedLeadAnalyzer().classify(context(text, "Плетёные кресла. Напишите + и получите каталог"))
    assert result and result.is_lead and result.intent == Intent.CONTACT
    assert result.lead_score < 70
    assert result.product_category == "RATTAN_ARMCHAIR"
    assert result.evidence and result.risk_flags


@pytest.mark.parametrize("caption", [
    "Плетёная мебель. Цена 100 + 50 за доставку", "Плетёная мебель. Телефон +998 00 000 00 00",
    "Плетёная мебель. Оставьте плюс, если понравилось", "Плетёная мебель. Каталог на сайте",
    "Напишите + для каталога iPhone", "Плетёная мебель. Каталог готов. Поставьте +, если нравится видео",
])
def test_a_plus_without_a_commercial_offer_is_not_invented_as_a_lead(caption):
    result = RuleBasedLeadAnalyzer().classify(context("+", caption))
    assert result is None or not result.is_lead


def test_unknown_product_in_a_commercial_plus_stays_under_assortment_review():
    ctx = context("+", "Отправьте нам + и мы рассчитаем стоимость мебели по вашим размерам")
    result = RuleBasedLeadAnalyzer().classify(ctx)
    assert result and result.is_lead and result.lead_score <= 60 and not result.is_commercial
    assert result.product_category is None


def test_reaction_parent_does_not_turn_a_plus_into_a_price_question():
    result = RuleBasedLeadAnalyzer().classify(context("+", "Плетёные кресла. Напишите + для каталога", "Красиво!"))
    assert result and result.intent == Intent.CONTACT and result.lead_score < 70
    result = RuleBasedLeadAnalyzer().classify(context("+", "Плетёные кресла", "Сколько стоит iPhone?"))
    assert result and not result.is_lead


@pytest.mark.parametrize("text", ["Salom", "Салом", "Assalomu alaykum!", "Здравствуйте 👋", "Vaau🔥"])
def test_greeting_alone_does_not_need_paid_ai(text):
    result = RuleBasedLeadAnalyzer().classify(context(text))
    assert result and not result.is_lead and result.intent == Intent.REACTION


@pytest.mark.parametrize("text", ["Salom, ratan stul narxi qancha?", "Здравствуйте, нужна доставка плетёных кресел"])
def test_greeting_does_not_hide_a_purchase_question(text):
    result = RuleBasedLeadAnalyzer().classify(context(text))
    assert result and result.is_lead


@pytest.mark.parametrize("text", [
    "Не нужны 20 диванов, хочу 2 пластиковых стула",
    "20 dona divan kerak emas, 2 dona ratan stul kerak",
])
def test_quantity_belongs_to_the_wanted_product(text):
    result = RuleBasedLeadAnalyzer().classify(context(text))
    assert result and result.is_lead and result.quantity == 2


def test_urgency_of_a_declined_item_does_not_raise_the_priority_of_the_order():
    result = RuleBasedLeadAnalyzer().classify(context("Не нужен диван сегодня, хочу плетёное кресло на следующий месяц"))
    assert result and result.is_lead and result.urgency.value != "HIGH"


def test_rejected_quantity_is_not_wholesale_evidence_for_other_services():
    result = B2BPolicy.assess("Для офиса не нужны 50 диванов, хочу 2 пластиковых стула", product="PLASTIC_CHAIRS")
    assert result.quantity == 2 and result.role.value == "B2C_CONSUMER"
    assert B2BPolicy.extract_quantity("50 плетёных кресел не нужны") is None


def test_requested_adjectives_do_not_hide_the_quantity_or_office_category():
    result = RuleBasedLeadAnalyzer().classify(context("Нужны 2 плетёных кресел"))
    assert result and result.quantity == 2 and result.product_category == "RATTAN_ARMCHAIR"
    assert assess_assortment("Два офисных кресел цена?", "Плетёная мебель").status == "EXCLUDED"


def score(history):
    return LeadScorerV3.score(is_lead=True, intent=Intent.DELIVERY, legacy_intent_score=70,
                             text="Доставка стульев", product="CHAIRS", evidence_ids=[1],
                             history=history, current_competitor="current", urgency_score=60,
                             now=datetime(2026, 10, 14, tzinfo=UTC))


def history(days, intent=Intent.AVAILABILITY):
    return HistoricalSignal("old_source", intent, CommercialSignalQuality.MEDIUM_COMMERCIAL,
                            datetime(2026, 10, 14, tzinfo=UTC) - timedelta(days=days))


def test_old_sequences_and_old_sources_lose_priority_together():
    recent, old = score([history(0)]), score([history(70)])
    assert recent.sequence_score > old.sequence_score
    assert recent.history_boost > old.history_boost
    assert recent.priority_score > old.priority_score


@pytest.mark.parametrize("days", [100, -100])
def test_expired_or_future_history_cannot_raise_priority(days):
    assert score([history(days)]) == score([])


@pytest.mark.parametrize("value", ["bad", "", None])
def test_invalid_history_date_is_not_treated_as_a_new_signal(value):
    assert parse_observed_at(value) is None


@pytest.mark.parametrize("changes", [
    {"evidence_ids": []}, {"vertical": "ARTIFICIAL_RATTAN"}, {"observed_at": "bad"},
    {"observed_at": "2099-01-01T00:00:00Z"},
])
def test_unverified_or_unrelated_history_cannot_boost_a_new_request(changes):
    ctx = context("Плетёное кресло цена?")
    item = ValidatedPreviousSignal(lead_id=1, public_signal_id=1, evidence_ids=[1], competitor_id=1,
                                  competitor="another", intent="CATALOG", product_family="RATTAN_ARMCHAIR",
                                  buyer_role="B2C_CONSUMER", commercial_quality="MEDIUM_COMMERCIAL",
                                  priority_score=80, confidence=80, observed_at=datetime.now(UTC).isoformat(),
                                  vertical="FURNITURE")
    ctx = replace(ctx, previous_signals=[replace(item, **changes)])
    result = RuleBasedLeadAnalyzer().classify(ctx)
    assert result.factors.history_boost == result.factors.sequence_score == 0
