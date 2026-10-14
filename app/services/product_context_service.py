"""Resolve the product named by a buyer before consulting publication context."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductContext:
    category: str | None = None
    categories: tuple[str, ...] = ()
    source: str | None = None
    negated_categories: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"version": "2.0", "category": self.category,
                "categories": list(self.categories), "source": self.source,
                "negated_categories": list(self.negated_categories)}


_FAMILIES = (
    ("COMPUTER_DESK", r"\b(?:компьютер\w*\s+стол\w*|письменн\w*\s+стол\w*|офисн\w*\s+стол\w*|(?:computer|office|writing)\s+desk\w*|kompyuter\w*\s+stol\w*)\b"),
    ("DRESSER", r"\b(?:комод\w*|komod\w*|dressers?)\b"),
    ("OFFICE_CHAIR", r"\b(?:(?:офисн\w*|компьютер\w*|игров\w*)\s+(?:крес(?:л|ел)\w*|стул\w*)|(?:office|gaming)\s+chairs?)\b"),
    ("WARDROBE", r"\b(?:шкаф\w*|shkaf\w*|wardrobes?)\b"),
    ("SHELVING", r"\b(?:стеллаж\w*|shelving|shelves)\b"),
    ("HALLWAY", r"\b(?:прихож\w*|hallway)\b"),
    ("LAMP", r"\b(?:ламп\w*|lamps?|lighting)\b"),
    ("KITCHEN_CABINET", r"\b(?:кухонн\w*\s+гарнитур\w*|kitchen\s+cabinets?|oshxona\s+mebel\w*)\b"),
    ("SOFA", r"\b(?:диван\w*|divan\w*|sofas?)\b"),
    ("BED", r"\b(?:кроват\w*|karavot\w*|karovat\w*|каравот\w*|beds?)\b"),
    ("ARMCHAIR", r"\b(?:крес(?:л|ел)\w*|kreslo\w*|armchairs?)\b"),
    ("CHAIRS", r"\b(?:стул\w*|стуль\w*|stul\w*|chairs?)\b"),
    ("TABLE", r"\b(?:стол(?:а|у|ом|ы|ов|ам|ами|ах|ик\w*|лар\w*|ни|нинг|га|да|дан|и)?|stol\w*|tables?)\b"),
    ("SWING", r"\b(?:качел\w*|swings?|хорч\w*)\b"),
    ("PERGOLA", r"\b(?:пергол\w*|pergolas?|беседк\w*)\b"),
)


def _normalize(text: str) -> str:
    text = (text or "").lower().replace("ё", "е")
    for apostrophe in ("‘", "’", "ʻ", "ʼ", "`"):
        text = text.replace(apostrophe, "'")
    return text


def _raw_mentions(text: str) -> list[tuple[int, int, str]]:
    matches = []
    occupied = []
    for category, pattern in _FAMILIES:
        for match in re.finditer(pattern, text):
            if not any(start <= match.start() and end >= match.end() for start, end in occupied):
                matches.append((match.start(), match.end(), category))
                occupied.append(match.span())
    return sorted(matches)


_MATERIAL_PATTERNS = {
    "RATTAN": r"ротанг|\b(?:rattan|ratan|rotang)\w*|плетен|плетение|pleten|to'qima|to'qilgan|тўқил",
    "PLASTIC": r"пластик|\b(?:plastic|plastik)\w*",
}


def _materials(text: str) -> set[str]:
    return {name for name, pattern in _MATERIAL_PATTERNS.items() if re.search(pattern, text)}


def _units(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;\n]|\s+(?:и|va|and|бн)\s+|\s*&\s*", text) if part.strip()]


def _is_negated(unit: str) -> bool:
    return re.search(
        r"\bне\s+(?:нуж\w*|надо|хочу|интересу\w*)\b|\b(?:kerak|керак)\s+(?:emas|эмас)\b|"
        r"(?:^|\bа\s+)не\s+(?:\w+\s+)?(?:диван\w*|стул\w*|стуль\w*|стол\w*|кресл\w*|комод\w*)\b",
        unit,
    ) is not None


def requested_product_clauses(text: str) -> list[str]:
    return [unit for unit in _units(_normalize(text)) if not _is_negated(unit)]


def _product_categories(text: str, *, include_negated: bool = False) -> tuple[str, ...]:
    text = _normalize(text)
    units = _units(text) if include_negated else requested_product_clauses(text)
    text = " ".join(units)
    all_materials = _materials(text)
    mentions = _raw_mentions(text)
    shared = set()
    if len(all_materials) == 1 and mentions:
        name = next(iter(all_materials))
        if re.search(_MATERIAL_PATTERNS[name], text).start() < mentions[0][0]:
            shared = all_materials
    categories = []
    for unit in units:
        material = _materials(unit)
        # A single shared material can describe a set. Distinct materials and
        # explicit upholstery must stay attached to their own product.
        if not material and shared and not re.search(r"мягк|обычн|обивк|ткан", unit):
            material = shared
        for _, _, category in _raw_mentions(unit):
            if category == "CHAIRS" and "PLASTIC" in material and "RATTAN" not in material:
                category = "PLASTIC_CHAIRS"
            elif len(material) == 1 and "RATTAN" in material:
                category = {"SOFA": "RATTAN_SOFA", "ARMCHAIR": "RATTAN_ARMCHAIR",
                            "CHAIRS": "RATTAN_CHAIR", "TABLE": "RATTAN_TABLE"}.get(category, category)
            if category in {"CHAIRS", "RATTAN_CHAIR"} and re.search(r"барн\w*\s+стул|барн\w*\s+стуль|bar\s+stool|высок\w*\s+стул|баркаунтер|bar\s+stol", unit):
                category = "RATTAN_BAR_STOOL"
            categories.append(category)
    families = tuple(dict.fromkeys(categories))
    dining = any(marker in text for marker in (
        "обеден", "dining", "стол со стул", "комплект стол", "komplekt stol",
    ))
    dining_families = { {"RATTAN_ARMCHAIR": "ARMCHAIR", "RATTAN_CHAIR": "CHAIRS",
                         "PLASTIC_CHAIRS": "CHAIRS", "RATTAN_TABLE": "TABLE"}.get(item, item) for item in families }
    if dining and dining_families.issubset({"TABLE", "CHAIRS", "ARMCHAIR"}):
        if not families or {"TABLE", "CHAIRS"}.issubset(dining_families) or "комплект" in text or "set" in text:
            return ("DINING_SET",)
        return tuple("DINING_CHAIRS" if item == "CHAIRS" else item for item in families)
    if not families and any(marker in text for marker in (
        "барный стул", "барные стулья", "bar stool", "высокий стул", "баркаунтер", "bar stol",
    )):
        # Preserve other requested products when a bar stool is part of an order.
        return ("RATTAN_BAR_STOOL",)
    rattan = all_materials == {"RATTAN"}
    if rattan:
        if set(families).issubset({"RATTAN_ARMCHAIR", "RATTAN_CHAIR", "RATTAN_TABLE"}) and any(marker in text for marker in (
            "гарнитур ротанг", "ротанг набор", "комплект ротанг",
            "rattan garden set", "rattan komplekt",
        )):
            return ("RATTAN_GARDEN_SET",)
        if not families and not _raw_mentions(text):
            return ("RATTAN_FURNITURE",)
    return families


def product_mentions(text: str) -> tuple[str, ...]:
    return _product_categories(text)


def positive_product_request_text(text: str) -> str:
    """Drop a rejected product clause only when another product is explicitly wanted."""
    units = _units(_normalize(text))
    wanted = [unit for unit in units if not _is_negated(unit) and _raw_mentions(unit)]
    if not any(re.search(r"\b(?:хочу|нуж\w*|куп\w*|заказ\w*|kerak|olmoqchiman|buyurtma)\b", unit) for unit in wanted):
        return text
    return " ".join(unit for unit in units if not _is_negated(unit))


def resolve_product_context(
    comment: str, post_caption: str, parent_comment: str = "",
) -> ProductContext:
    for source, text in (("COMMENT", comment), ("PARENT_COMMENT", parent_comment),
                         ("POST_CAPTION", post_caption)):
        categories = product_mentions(text)
        negated = tuple(item for item in _product_categories(text, include_negated=True) if item not in categories)
        if source in {"COMMENT", "PARENT_COMMENT"} and set(categories) & {"ARMCHAIR", "CHAIRS", "TABLE"}:
            for context_text in (parent_comment, post_caption) if source == "COMMENT" else (post_caption,):
                context_categories = product_mentions(context_text)
                inherited = []
                for category in categories:
                    compatible = {"ARMCHAIR": {"RATTAN_ARMCHAIR"},
                                  "CHAIRS": {"RATTAN_CHAIR", "PLASTIC_CHAIRS", "DINING_CHAIRS", "RATTAN_BAR_STOOL"},
                                  "TABLE": {"RATTAN_TABLE"}}.get(category, set())
                    choices = compatible & set(context_categories)
                    if not re.search(r"мягк|обычн|обивк|ткан", _normalize(text)) and category not in context_categories:
                        if len(choices) == 1:
                            category = next(iter(choices))
                        elif context_categories == ("RATTAN_FURNITURE",):
                            category = {"ARMCHAIR": "RATTAN_ARMCHAIR", "CHAIRS": "RATTAN_CHAIR", "TABLE": "RATTAN_TABLE"}.get(category, category)
                    inherited.append(category)
                categories = tuple(dict.fromkeys(inherited))
        if categories or negated:
            category = categories[0] if len(categories) == 1 else (
                "MIXED_FURNITURE" if source == "COMMENT" else None
            ) if categories else None
            return ProductContext(category, categories, source, negated)
    return ProductContext()
