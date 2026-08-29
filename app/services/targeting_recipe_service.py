"""Meta-safe targeting recipes built only from validated catalog IDs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TargetingRecipe:
    recipe_type: str
    name: str
    interest_ids: tuple[str, ...]
    excluded_interest_ids: tuple[str, ...]
    broad_targeting: bool
    age_policy: str
    status: str
    reason: str


class TargetingRecipeEngine:
    @classmethod
    def generate_recipes(
        cls,
        *,
        audience_name: str,
        top_category: str = "DINING_SET",
        buyer_role: str = "B2C_CONSUMER",
        validated_interest_ids: tuple[str, ...] = (),
        meta_connected: bool = False,
    ) -> list[TargetingRecipe]:
        del top_category, buyer_role
        status = "DRAFT" if meta_connected else "NOT_CONNECTED"
        reason = (
            "Используются только validated interest IDs текущего Meta catalog."
            if meta_connected
            else "Meta не подключена; interest IDs и внешние audience IDs не создавались."
        )
        ids = tuple(dict.fromkeys(str(value) for value in validated_interest_ids if value))
        return [
            TargetingRecipe(
                recipe_type=strategy,
                name=f"{label}: {audience_name}",
                interest_ids=ids if strategy != "BROAD" else (),
                excluded_interest_ids=(),
                broad_targeting=strategy == "BROAD",
                age_policy="BROAD_UNLESS_BUSINESS_JUSTIFIED",
                status=status,
                reason=reason,
            )
            for strategy, label in (
                ("NARROW", "Точный план"),
                ("BALANCED", "Сбалансированный план"),
                ("BROAD", "Широкий план"),
            )
        ]
