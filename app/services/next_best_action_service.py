from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.db.models import Product
from app.services.b2b_policy import B2BPolicy


@dataclass(frozen=True, slots=True)
class ActionRecommendation:
    action_type: str
    title: str
    description: str
    recommended_product_id: int | None
    recommended_sku: str | None
    urgency: str
    evidence_ids: Sequence[int]
    match_score: int | None
    match_reasons: Sequence[str]
    ranked_product_ids: Sequence[int]


@dataclass(frozen=True, slots=True)
class RankedProduct:
    product: Product
    score: int
    reasons: Sequence[str]


class NextBestActionEngine:
    """Produces actions grounded only in lead evidence and persisted catalog facts."""

    @classmethod
    def recommend(
        cls,
        *,
        buyer_role: str,
        intent: str,
        product_category: str | None,
        lead_score: int,
        competitor_count: int = 1,
        quantity: int | None = None,
        evidence_ids: Sequence[int] = (),
        catalog_products: Sequence[RankedProduct] = (),
    ) -> ActionRecommendation:
        evidence_list = list(evidence_ids)
        selected = catalog_products[0] if catalog_products else None
        product = selected.product if selected is not None else None

        if buyer_role == "B2B_HORECA" or (
            quantity and quantity >= B2BPolicy.PROBABLE_QUANTITY
        ):
            quantity_text = f" ({quantity} ед.)" if quantity else ""
            description = (
                "Подтвердить модель, количество, актуальную цену, наличие и срок поставки. "
                "Коммерческие условия и остаток проверить по каталогу перед ответом."
            )
            if product is not None:
                description = cls._catalog_description(product, prefix="Подготовить расчёт")
            return cls._result(
                action_type="B2B_PROPOSAL",
                title=f"Уточнить объём и подготовить B2B-расчёт{quantity_text}",
                description=description,
                candidate=selected,
                ranked_products=catalog_products,
                urgency="HIGH",
                evidence_ids=evidence_list,
            )

        if competitor_count >= 2:
            return cls._result(
                action_type="CALL",
                title="Связаться сегодня: клиент сравнивает предложения",
                description=(
                    f"Есть подтверждённый коммерческий интерес у {competitor_count} компаний. "
                    "Уточнить критерии выбора и только затем предложить подтверждённую модель."
                ),
                candidate=selected,
                ranked_products=catalog_products,
                urgency="HIGH",
                evidence_ids=evidence_list,
            )

        if buyer_role == "DESIGNER_CONTRACTOR":
            return cls._result(
                action_type="QUESTION",
                title="Уточнить спецификацию проекта",
                description=(
                    "Запросить категорию, количество, размеры и срок проекта. "
                    "3D-модели и агентские условия не подтверждены в каталоге."
                ),
                candidate=selected,
                ranked_products=catalog_products,
                urgency="MEDIUM",
                evidence_ids=evidence_list,
            )

        if product is not None and intent in {"PRICE", "AVAILABILITY", "BUY", "CATALOG"}:
            return cls._result(
                action_type="OFFER",
                title=f"Проверить и предложить {product.name}",
                description=cls._catalog_description(product),
                candidate=selected,
                ranked_products=catalog_products,
                urgency="HIGH" if lead_score >= 80 else "MEDIUM",
                evidence_ids=evidence_list,
            )

        product_text = f" по категории {product_category}" if product_category else ""
        return cls._result(
            action_type="QUESTION",
            title=f"Уточнить нужную модель и параметры{product_text}",
            description=(
                "Подходящий подтверждённый товар пока не сопоставлен. "
                "Уточнить количество, размеры и цвет; наличие проверить перед предложением."
            ),
            candidate=None,
            ranked_products=catalog_products,
            urgency="MEDIUM" if lead_score >= 70 else "LOW",
            evidence_ids=evidence_list,
        )

    @staticmethod
    def _catalog_description(product: Product, *, prefix: str = "Подтвердить предложение") -> str:
        facts = [f"цена {product.price} {product.currency}" if product.price is not None else None]
        if product.minimum_order_quantity is not None:
            facts.append(f"MOQ {product.minimum_order_quantity}")
        facts_text = ", ".join(fact for fact in facts if fact)
        stock_text = (
            f"Подтверждённый остаток: {product.stock}."
            if product.stock is not None
            else "Наличие не подтверждено — проверить перед ответом."
        )
        return f"{prefix}: {facts_text}. {stock_text}" if facts_text else f"{prefix}. {stock_text}"

    @staticmethod
    def _result(
        *,
        action_type: str,
        title: str,
        description: str,
        candidate: RankedProduct | None,
        ranked_products: Sequence[RankedProduct],
        urgency: str,
        evidence_ids: Sequence[int],
    ) -> ActionRecommendation:
        product = candidate.product if candidate is not None else None
        return ActionRecommendation(
            action_type=action_type,
            title=title,
            description=description,
            recommended_product_id=product.id if product is not None else None,
            recommended_sku=product.sku if product is not None else None,
            urgency=urgency,
            evidence_ids=evidence_ids,
            match_score=candidate.score if candidate is not None else None,
            match_reasons=tuple(candidate.reasons) if candidate is not None else (),
            ranked_product_ids=tuple(item.product.id for item in ranked_products[:3]),
        )
