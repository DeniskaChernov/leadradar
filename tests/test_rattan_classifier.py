"""
test_rattan_classifier.py — Tests for V6 Rattan Business Role & Reseller/Wholesaler Classifier.
"""

from __future__ import annotations

from app.services.rattan_classifier_service import RattanBusinessClassifier


def test_classify_raw_rattan_wholesaler():
    text = "Искусственный ротанг для плетения оптом в бухтах по 10 кг. Размеры 6 мм и 8 мм полукруг. Минимальный заказ от 50 кг."
    res = RattanBusinessClassifier.classify_text(text)
    assert res.primary_role == "RAW_RATTAN_WHOLESALER"
    assert res.confidence >= 80
    assert res.wholesaler_probability >= 0.6
    assert "ev_raw_rattan_terms" in res.evidence_ids
    assert "ev_wholesale_terms" in res.evidence_ids
    assert "ev_profile_specifications" in res.evidence_ids


def test_classify_rattan_manufacturer():
    text = "Собственное производство и плетение мебели из ротанга. Изготовление на заказ в нашем цехе."
    res = RattanBusinessClassifier.classify_text(text)
    assert res.primary_role == "RATTAN_FURNITURE_MANUFACTURER"
    assert res.manufacturer_probability >= 0.5
    assert "ev_manufacturing_terms" in res.evidence_ids


def test_classify_raw_rattan_buyer():
    text = "Куплю искусственный ротанг 8 мм полукруг, нужен ротанг для производства диванов."
    res = RattanBusinessClassifier.classify_text(text)
    assert res.primary_role == "RAW_RATTAN_BUYER"
    assert res.buyer_probability >= 0.7


def test_classify_finished_furniture_reseller():
    text = "Плетёный диван и кресло из ротанга для сада. Цена 3 500 000 сум."
    res = RattanBusinessClassifier.classify_text(text)
    assert res.primary_role == "RATTAN_FURNITURE_RESELLER"
    assert "ev_no_raw_rattan_materials" in res.negative_evidence_ids
