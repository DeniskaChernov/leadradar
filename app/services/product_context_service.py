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
        return {"version": "1.1", "category": self.category,
                "categories": list(self.categories), "source": self.source}


_FAMILIES = (
    ("COMPUTER_DESK", r"\b(?:компьютер\w*\s+стол\w*|письменн\w*\s+стол\w*|офисн\w*\s+стол\w*|(?:computer|office|writing)\s+desk\w*|kompyuter\w*\s+stol\w*)\b"),
    ("DRESSER", r"\b(?:комод\w*|komod\w*|dressers?)\b"),
    ("OFFICE_CHAIR", r"\b(?:(?:офисн\w*|компьютер\w*|игров\w*)\s+(?:кресл\w*|стул\w*)|(?:office|gaming)\s+chairs?)\b"),
    ("WARDROBE", r"\b(?:шкаф\w*|shkaf\w*|wardrobes?)\b"),
    ("SHELVING", r"\b(?:стеллаж\w*|shelving|shelves)\b"),
    ("HALLWAY", r"\b(?:прихож\w*|hallway)\b"),
    ("LAMP", r"\b(?:ламп\w*|lamps?|lighting)\b"),
    ("KITCHEN_CABINET", r"\b(?:кухонн\w*\s+гарнитур\w*|kitchen\s+cabinets?|oshxona\s+mebel\w*)\b"),
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
    for apostrophe in ("‘", "’", "ʻ", "ʼ", "`"):
        text = text.replace(apostrophe, "'")
    matches = []
    occupied = []
    for category, pattern in _FAMILIES:
        for match in re.finditer(pattern, text):
            if not any(start <= match.start() and end >= match.end() for start, end in occupied):
                matches.append((match.start(), category))
                occupied.append(match.span())
    families = tuple(dict.fromkeys(category for _, category in sorted(matches)))
    dining = any(marker in text for marker in (
        "обеден", "dining", "стол со стул", "комплект стол", "komplekt stol",
    ))
    if dining and set(families).issubset({"TABLE", "CHAIRS", "ARMCHAIR"}):
        if not families or {"TABLE", "CHAIRS"}.issubset(families) or "комплект" in text or "set" in text:
            return ("DINING_SET",)
        return tuple("DINING_CHAIRS" if item == "CHAIRS" else item for item in families)
    if "CHAIRS" in families and any(marker in text for marker in ("пластик", "plastic", "plastik")):
        return tuple("PLASTIC_CHAIRS" if item == "CHAIRS" else item for item in families)
    if any(marker in text for marker in (
        "барный стул", "барные стулья", "bar stool", "высокий стул", "баркаунтер", "bar stol",
    )):
        # Preserve other requested products when a bar stool is part of an order.
        return tuple("RATTAN_BAR_STOOL" if item == "CHAIRS" else item for item in families) or ("RATTAN_BAR_STOOL",)
    rattan = any(marker in text for marker in ("ротанг", "rattan", "ratan", "rotang", "плетен", "плетение", "pleten", "to'qima", "to'qilgan", "тўқил"))
    if rattan:
        if set(families).issubset({"ARMCHAIR", "CHAIRS", "TABLE"}) and any(marker in text for marker in (
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
        if source in {"COMMENT", "PARENT_COMMENT"} and set(categories) & {"ARMCHAIR", "CHAIRS", "TABLE"}:
            modifiers = " ".join(word for word in ("ротанг", "rattan", "ratan", "rotang", "плетен", "пластик", "plastic", "plastik", "обеден")
                                 if word in (parent_comment + " " + post_caption).lower())
            if modifiers:
                categories = product_mentions(f"{text} {modifiers}")
        if categories:
            category = categories[0] if len(categories) == 1 else (
                "MIXED_FURNITURE" if source == "COMMENT" else None
            )
            return ProductContext(category, categories, source)
    return ProductContext()
