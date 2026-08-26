from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CompetitorSeed:
    handle: str
    display_name: str
    category: str
    tier: str
    notes: str
    website_url: str = ""
    active_by_default: bool = False


@dataclass(frozen=True, slots=True)
class MarketCandidateSeed:
    display_name: str
    category: str
    tier: str
    rationale: str
    website_url: str = ""
    instagram_handle: str = ""
    confidence: int = 50


# Handles in this list were verified from official sites / public business pages during the
# market-research pass. New seeds are deliberately paused by default: appearing in the registry
# must never silently increase paid Instagram traffic.
MONITORED_COMPETITORS: tuple[CompetitorSeed, ...] = (
    CompetitorSeed(
        "aiko.uz", "AIKO", "DIRECT", "A",
        "Прямой конкурент: плетёная мебель, столы, стулья, обеденные и outdoor-комплекты.",
        "https://aiko.uz", True,
    ),
    CompetitorSeed(
        "chinar.uz", "CHINAR", "DIRECT", "A",
        "Прямой конкурент: искусственный ротанг, комплекты для дома, террасы, кафе и ресторанов.",
        "https://chinar.uz",
    ),
    CompetitorSeed(
        "rona_rattan.uz", "Rona Rattan", "DIRECT", "A",
        "Натуральный ротанг и готовые комплекты; близкая аудитория по плетёной мебели.",
        "https://rattan.uz/mebelrotang",
    ),
    CompetitorSeed(
        "dafnamebel", "DAFNA", "DINING", "A",
        "Крупный мебельный бренд: дом, кафе, рестораны, столы и стулья. Высокий объём аудитории.",
        "https://dafna.uz",
    ),
    CompetitorSeed(
        "mebel__house__", "Mebel House", "OUTDOOR", "A",
        "Садовая мебель, искусственный ротанг и кухонные обеденные комплекты.",
    ),
    CompetitorSeed(
        "atlasmebeluz", "Atlas Mebel", "MASS", "B",
        "Крупный мебельный маркет; агрегирует множество брендов, столы и стулья, outdoor.",
        "https://atlasgroup.uz",
    ),
    CompetitorSeed(
        "homemarketuz", "Home Market", "MASS", "B",
        "Большой поток аудитории товаров для дома и мебели; источник смежного спроса.",
        "https://hm.uz",
    ),
    CompetitorSeed(
        "comfort_mebel_2018", "Comfort Mebel", "DINING", "B",
        "Мебель для дома, столы и стулья; массовый спрос и ценовые комментарии.",
        "https://comfort-mebel.uz",
    ),
    CompetitorSeed(
        "fullhouse.uz", "FullHouse", "DINING", "B",
        "Мебель для дома и кухни, отдельная категория столов и стульев.",
        "https://fullhouse.uz",
    ),
    CompetitorSeed(
        "weltewhome_tashkent", "Weltew Home", "PREMIUM", "B",
        "Dining Room и интерьерные комплекты; премиальный смежный спрос.",
        "https://weltewhome.uz",
    ),
    CompetitorSeed(
        "mebelpark.uz", "Mebel Park", "MASS", "C",
        "Мебельный магазин с широкой аудиторией; полезен как дополнительный источник спроса.",
        "https://mebelpark.uz",
    ),
)


# Market candidates are useful competitors/brands whose current Instagram handle still needs
# verification before we allow a paid provider to monitor it. Keeping them inside the product
# prevents the market map from living in somebody's notes or memory.
MARKET_CANDIDATES: tuple[MarketCandidateSeed, ...] = (
    MarketCandidateSeed("Lazuno Ok", "DIRECT", "A", "Искусственный ротанг, столы, стулья и комплекты.", "https://lazunok.uz", confidence=95),
    MarketCandidateSeed("Rotan", "DIRECT", "A", "Производство искусственного ротанга, столовая и HoReCa.", "https://rotan.uz", confidence=95),
    MarketCandidateSeed("Rotang Asia", "DIRECT", "A", "Бренд искусственного ротанга, представлен в Atlas Mebel.", confidence=85),
    MarketCandidateSeed("Miss Madi", "OUTDOOR", "B", "Бренд дачной мебели, отмечен среди outdoor-брендов Atlas Mebel.", confidence=65),
    MarketCandidateSeed("Mudo Concept", "PREMIUM", "B", "Интерьерные и dining-товары, премиальная аудитория.", "https://mudo.uz", "mudoconcept", 70),
    MarketCandidateSeed("Homedit", "DINING", "B", "Большой ассортимент обеденных столов и мебели для кухни.", "https://homedit.uz", confidence=85),
    MarketCandidateSeed("Divanchi", "DINING", "B", "Столы, стулья, кухни и мягкая мебель; смежная аудитория.", instagram_handle="divanchi.uz", confidence=75),
    MarketCandidateSeed("Focus Mebel", "MASS", "C", "Крупный мебельный салон с кухонной мебелью и широким ассортиментом.", instagram_handle="focus.mebel", confidence=75),
    MarketCandidateSeed("Mogno Mebel", "PREMIUM", "C", "Премиальная интерьерная мебель.", instagram_handle="mogno_mebel_uz", confidence=75),
    MarketCandidateSeed("Rich House", "DINING", "C", "Мебель для дома; бренд представлен в Atlas Mebel.", confidence=60),
    MarketCandidateSeed("Woodline", "MASS", "C", "Популярный мебельный продавец по пользовательским рейтингам рынка.", confidence=55),
    MarketCandidateSeed("Arca Mebel", "MASS", "C", "Крупный мебельный центр и источник массового мебельного спроса.", confidence=55),
    MarketCandidateSeed("My Sofa", "MASS", "C", "Популярный мебельный бренд, смежная аудитория.", confidence=50),
    MarketCandidateSeed("Azbuka Doma", "PREMIUM", "C", "Интерьерный бренд, представлен в Atlas Mebel.", confidence=55),
    MarketCandidateSeed("Sofia Mebel", "MASS", "C", "Мебель для дома, смежная аудитория.", confidence=50),
    MarketCandidateSeed("Divan.uz", "MASS", "C", "Крупный онлайн-каталог мебели, потенциальный источник массового спроса.", "https://divan.uz", confidence=65),
    MarketCandidateSeed("Premium Garden", "OUTDOOR", "B", "Садовая и outdoor-мебель; релевантный сегмент.", confidence=55),
    MarketCandidateSeed("Treet", "HORECA", "B", "HoReCa-мебель и коммерческие проекты; потенциально высокий средний чек.", confidence=55),
    MarketCandidateSeed("Bellezzio", "DINING", "B", "Столы и стулья; бренд встречается в мебельном ассортименте Atlas Mebel.", confidence=60),
    MarketCandidateSeed("KINGLAND", "DINING", "B", "Стулья и посадочная мебель; релевантен покупателям обеденной зоны.", confidence=60),
    MarketCandidateSeed("INTERMEBEL", "MASS", "C", "Мебель для дома; присутствует среди брендов крупного мебельного рынка.", confidence=50),
    MarketCandidateSeed("MAXIMUM", "MASS", "C", "Мебель для дома; дополнительный источник массового мебельного спроса.", confidence=50),
    MarketCandidateSeed("Famous Mebel", "MASS", "C", "Мебель для дома и гостиной; смежная аудитория покупателей мебели.", confidence=55),
    MarketCandidateSeed("Mondelux", "PREMIUM", "C", "Интерьерная мебель; смежная премиальная аудитория.", confidence=50),
    MarketCandidateSeed("Elite Home", "PREMIUM", "C", "Интерьерная мебель для дома; дополнительный премиальный сегмент.", confidence=50),
    MarketCandidateSeed("Wood&Loft", "DINING", "C", "Мебель в loft-стиле; потенциально релевантны столы и обеденные зоны.", confidence=50),
    MarketCandidateSeed("Sora Mebel", "MASS", "C", "Мебель для дома; дополнительный источник аудитории мебельного рынка.", confidence=50),
)
