"""Resolve the product named by a buyer before consulting publication context."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductContext:
    category: str | None = None
    categories: tuple[str, ...] = ()
    source: str | None = None

    def as_dict(self) -> dict:
        return {"version": "1.0", "category": self.category,
                "categories": list(self.categories), "source": self.source}


_FAMILIES = (
    ("SOFA", r"\b(?:диван\w*|divan\w*|sofas?)\b"),
    ("BED", r"\b(?:кроват\w*|karavot\w*|karovat\w*|каравот\w*|beds?)\b"),
    ("ARMCHAIR", r"\b(?:кресл\w*|kreslo\w*|armchairs?)\b"),
    ("CHAIRS", r"\b(?:стул\w*|стуль\w*|stul\w*|chairs?)\b"),
    ("TABLE", r"\b(?:стол(?:а|у|ом|ы|ов|ам|ами|ах|ик\w*|лар\w*|ни|нинг|га|да|дан|и)?|stol\w*|tables?)\b"),
    ("SWING", r"\b(?:качел\w*|swings?|хорч\w*)\b"),
    ("PERGOLA", r"\b(?:пергол\w*|pergolas?|беседк\w*)\b"),
)


def product_mentions(text: str) -> tuple[str, ...]:
    text = (text or "").lower().replace("ё", "е")
    matches = [(match.start(), category) for category, pattern in _FAMILIES
               for match in re.finditer(pattern, text)]
    families = tuple(dict.fromkeys(category for _, category in sorted(matches)))
    dining = any(marker in text for marker in (
        "обеден", "dining", "стол со стул", "комплект стол", "komplekt stol",
    ))
    if dining and set(families).issubset({"TABLE", "CHAIRS", "ARMCHAIR"}):
        return ("DINING_SET",)
    if any(marker in text for marker in (
        "барный стул", "барные стулья", "bar stool", "высокий стул", "баркаунтер", "bar stol",
    )):
        return ("RATTAN_BAR_STOOL",)  # Preserve the existing bar-stool taxonomy.
    rattan = any(marker in text for marker in ("ротанг", "rattan", "плетен"))
    if rattan:
        if any(marker in text for marker in (
            "гарнитур ротанг", "ротанг набор", "комплект ротанг",
            "rattan garden set", "rattan komplekt",
        )):
            return ("RATTAN_GARDEN_SET",)
        aliases = {"SOFA": "RATTAN_SOFA", "ARMCHAIR": "RATTAN_ARMCHAIR",
                   "CHAIRS": "RATTAN_CHAIR", "TABLE": "RATTAN_TABLE"}
        return tuple(aliases.get(item, item) for item in families) or ("RATTAN_FURNITURE",)
    return families


def resolve_product_context(
    comment: str, post_caption: str, parent_comment: str = "",
) -> ProductContext:
    for source, text in (("COMMENT", comment), ("PARENT_COMMENT", parent_comment),
                         ("POST_CAPTION", post_caption)):
        categories = product_mentions(text)
        if categories:
            category = categories[0] if len(categories) == 1 else (
                "MIXED_FURNITURE" if source == "COMMENT" else None
            )
            return ProductContext(category, categories, source)
    return ProductContext()
