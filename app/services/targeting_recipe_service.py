"""
targeting_recipe_service.py — V6 Meta Ads Targeting Recipe Engine.

Generates 3 Meta Ads targeting recipes (NARROW, BALANCED, BROAD) based on Audience DNA:
  - Primary & secondary Meta interest candidates
  - Creative angles & offers
  - CTA & landing page recommendations
  - Experiment hypothesis
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TargetingRecipe:
    recipe_type: str  # NARROW, BALANCED, BROAD
    name: str
    primary_interests: Sequence[str]
    secondary_interests: Sequence[str]
    excluded_interests: Sequence[str]
    creative_angle: str
    offer: str
    cta: str
    landing_page: str
    hypothesis: str


class TargetingRecipeEngine:
    """Generates policy-compliant Meta Ads targeting recipes grounded in Audience DNA."""

    @classmethod
    def generate_recipes(
        cls,
        *,
        audience_name: str,
        top_category: str = "DINING_SET",
        buyer_role: str = "B2C_CONSUMER",
    ) -> list[TargetingRecipe]:
        recipes: list[TargetingRecipe] = []

        # 1. NARROW Recipe (High Precision)
        recipes.append(
            TargetingRecipe(
                recipe_type="NARROW",
                name=f"Точный рецепт: {audience_name}",
                primary_interests=["Garden furniture", "Patio (furniture)", "Outdoor dining"],
                secondary_interests=["Interior design", "Home improvement"],
                excluded_interests=["Used furniture", "Second-hand"],
                creative_angle="Премиальное плетёное качество с гарантийной защитой от выгорания",
                offer="Комплект 6 плетёных стульев + обеденный стол с бесплатной доставкой",
                cta="Получить каталог в WhatsApp",
                landing_page="/dining-sets",
                hypothesis="Высокоточный таргетинг на покупателей загородных комплектов даст максимальную конверсию в заявку.",
            )
        )

        # 2. BALANCED Recipe (Scale + Precision)
        recipes.append(
            TargetingRecipe(
                recipe_type="BALANCED",
                name=f"Сбалансированный рецепт: {audience_name}",
                primary_interests=["Furniture", "Outdoor recreation", "Terrace (building)"],
                secondary_interests=["Home decor", "Landscape architecture"],
                excluded_interests=[],
                creative_angle="Современная мебель для веранды и террасы с прямыми ценами от производителя",
                offer="Скидка 15% при заказе обеденного гарнитура до конца недели",
                cta="Посмотреть каталог",
                landing_page="/catalog",
                hypothesis="Баланс целевых интересов мебели и террас обеспечит оптимальную стоимость лида (CPL).",
            )
        )

        # 3. BROAD Recipe (Maximum Reach / Advantage+)
        recipes.append(
            TargetingRecipe(
                recipe_type="BROAD",
                name=f"Широкий рецепт (Broad / Advantage+): {audience_name}",
                primary_interests=["Home & Garden", "Lifestyle"],
                secondary_interests=[],
                excluded_interests=[],
                creative_angle="Видео-обзор комфорта плетёного кресла в реальном интерьере",
                offer="Закажите выезд дизайнера с образцами ротанга",
                cta="Подробнее",
                landing_page="/home",
                hypothesis="Широкий охват с сильным видео-креативом позволит алгоритмам Meta самостоятельно найти покупателей.",
            )
        )

        return recipes
