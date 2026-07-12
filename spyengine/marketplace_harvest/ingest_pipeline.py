from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .canonicalize import canonicalize_product, canonicalize_title


COMMON_SIMPLE_TERMS: dict[str, list[str]] = {
    "technology_gpu": ["scheda video", "gpu", "video card", "graphics card", "vga"],
    "technology_ram": ["ram", "memoria", "banco", "modulo", "stick", "memory"],
    "technology_smartphone": ["telefono", "smartphone", "cellulare", "phone", "mobile"],
    "technology_phone": ["telefono", "smartphone", "cellulare", "phone", "mobile"],
    "technology_tablet": ["tablet", "ipad", "galaxy tab"],
    "technology_monitor": ["monitor", "display", "screen", "schermo"],
    "technology_desktop_pc": ["desktop pc", "mini pc", "computer fisso"],
    "technology_audio_amplifier": ["amplificatore", "amplifier", "amplificador", "pedalera"],
    "home_decor_photo_frame": ["cornice", "fotolijst", "photo frame", "picture frame"],
    "home_decor_wall_art": ["quadro", "poster", "wall art", "stampa"],
    "home_furniture_table": ["tavolo", "table", "tisch", "pöytä"],
    "home_storage_container": ["contenitore", "vorratsdose", "storage container", "ikea"],
    "school_bag": ["zaino scuola", "school bag", "skoletaske"],
    "sports_billiards": ["biliardo", "billiard", "biljardbord", "pool table"],
    "sports_fishing_lure": ["wobbler", "fishing lure", "esca"],
    "toys_lego": ["lego", "minifigure", "playmobil"],
    "tools_measuring_caliper": ["calibro", "caliper", "skjutmått", "schieblehre"],
    "tools_cutting_tool": ["fresa", "modulfräser", "milling cutter"],
    "vehicle_car_part": ["ricambio auto", "car part", "kompresor klimatyzacji"],
    "vehicle_motorcycle_accessory": ["baule moto", "baúl de moto", "top case"],
    "vehicle_car": ["auto", "car", "voiture", "coche", "samochod"],
    "fashion_clothing": ["abbigliamento", "polo", "shirt", "maglia", "clothing"],
    "books_media_book": ["libro", "book", "buch"],
    "home_plumbing_faucets": ["rubinetto", "miscelatore", "lavabo", "doccia", "faucet", "tap"],
    "home_appliances": ["elettrodomestico", "aspirapolvere", "vacuum cleaner", "floorcare"],
    "tools_battery": ["trapano", "avvitatore", "batteria", "drill", "driver"],
}


@dataclass
class CleanDecision:
    decision: str
    confidence: float
    reason: str
    normalized_title: str = ""
    normalized_category: str = ""
    warnings: list[str] = field(default_factory=list)
    common_terms: list[str] = field(default_factory=list)


_CATEGORY_URL_RE = re.compile(
    r"(/c/|/category|/categories|/categorie|/categoria|/catalog|/catalogo|/search|/recherche|/zoeken|/collections?$|/products/?$|/deals/?$)",
    re.I,
)
_PRODUCT_URL_RE = re.compile(
    r"(/p/|/product/|/products/[^/?#]+|/item/|/itm/|/ad/|/ads/|/annunci/|/anzeige/|/oferta|/oferty/|/listing|/listings|/product-detail)",
    re.I,
)
_GENERIC_CATEGORY_TITLE_RE = re.compile(
    r"^(google phones|samsung phones|apple phones|iphones|smartphones?|phones?|cellulari|telefoni|"
    r"laptops?|portatili|tablets?|smartwatches?|headphones?|cuffie|accessories|accessori|"
    r"computer accessories|smartphone accessories|all categories|view all|show all)$",
    re.I,
)
_MARKETING_PREFIX_RE = re.compile(
    r"^(bestseller|just a few left|pochi pezzi rimasti|solo pochi rimasti|deal|offerta|new|nuovo)\s+",
    re.I,
)
_RATING_BEFORE_PRICE_RE = re.compile(
    r"\b[0-5](?:[,.][0-9])?\s*(?=(?:€|eur|euro|chf|£|gbp|\$|usd)\s*\d|\d{2,}[,.]?\d*\s*(?:€|eur|euro|chf|£|gbp|\$|usd))",
    re.I,
)
_CURRENCY_PREFIX_PRICE_RE = re.compile(
    r"(?:€|eur|euro|chf|£|gbp|\$|usd)\s*[0-9][0-9.,]*",
    re.I,
)
_CURRENCY_SUFFIX_PRICE_RE = re.compile(
    r"[0-9][0-9.,]*\s*(?:€|eur|euro|chf|£|gbp|\$|usd)",
    re.I,
)
_CONDITION_RE = re.compile(r"\((new|nuovo|used|usato|refurbished|ricondizionato)\)", re.I)


def simple_terms_for_category(category: str) -> list[str]:
    return COMMON_SIMPLE_TERMS.get(category, [])


def is_category_or_nav_url(url: str) -> bool:
    return bool(_CATEGORY_URL_RE.search(url or "")) and not bool(_PRODUCT_URL_RE.search(url or ""))


def is_product_url(url: str) -> bool:
    return bool(_PRODUCT_URL_RE.search(url or ""))


def is_generic_category_title(title: str) -> bool:
    title_s = re.sub(r"\s+", " ", title or "").strip()
    return bool(_GENERIC_CATEGORY_TITLE_RE.match(title_s))


def normalize_listing_title(title: str) -> str:
    return canonicalize_title(title)


def has_model_specificity(title: str, url: str = "") -> bool:
    text = f"{title} {url}".lower()
    return bool(
        re.search(r"\b(pixel|iphone|ipad|macbook|galaxy|thinkpad|rtx|gtx|rx)\s*[a-z]*\s*\d+[a-z]*\b", text)
        or re.search(r"\b[a-z]{2,}[-\s]?\d{2,}[a-z0-9-]*\b", text)
        or re.search(r"\b\d{2,}[a-z]{1,4}\b", text)
    )


def deterministic_clean_decision(
    title: str,
    category: str = "",
    raw_quality: dict[str, Any] | None = None,
    url: str = "",
) -> CleanDecision:
    """Mandatory deterministic reasoning gate before online verification."""

    title = (title or "").strip()
    title_l = title.lower()
    quality = raw_quality or {}
    reason = str(quality.get("reason") or "")
    normalized = normalize_listing_title(title)
    canonical = canonicalize_product(normalized, category)

    junk_markers = [
        "view all",
        "all categories",
        "privacy",
        "cookie",
        "newsletter",
        "mon - fri",
        "0800 222",
        "apple weeks smartphones",
    ]

    if any(x in title_l for x in junk_markers):
        return CleanDecision("reject", 0.97, "junk_marker", normalized_title=normalized, normalized_category=canonical.category, warnings=["nav_or_footer_noise"], common_terms=simple_terms_for_category(category))

    if is_category_or_nav_url(url):
        return CleanDecision("reject", 0.98, "category_url_not_listing", normalized_title=normalized, normalized_category=canonical.category, warnings=["category_url"], common_terms=simple_terms_for_category(category))

    if is_generic_category_title(normalized) and not has_model_specificity(normalized, url):
        return CleanDecision("reject", 0.96, "generic_category_title", normalized_title=normalized, normalized_category=canonical.category, warnings=["generic_title"], common_terms=simple_terms_for_category(category))

    if reason in {"category_or_nav_url", "nav_title", "noise_title", "weak_generic_anchor"}:
        return CleanDecision("reject", 0.92, reason, normalized_title=normalized, normalized_category=canonical.category, common_terms=simple_terms_for_category(category))

    if len(normalized) < 6:
        return CleanDecision("reject", 0.88, "title_too_short", normalized_title=normalized, normalized_category=canonical.category, common_terms=simple_terms_for_category(category))

    if reason == "price_card":
        return CleanDecision("accept", 0.84, "price_card", normalized_title=normalized, normalized_category=canonical.category, common_terms=simple_terms_for_category(category))

    if is_product_url(url) and has_model_specificity(normalized, url):
        return CleanDecision("accept", 0.80, "product_url_model_specific", normalized_title=normalized, normalized_category=canonical.category, common_terms=simple_terms_for_category(category))

    if reason == "product_url":
        return CleanDecision("uncertain", 0.58, "product_url_needs_reasoning", normalized_title=normalized, normalized_category=canonical.category, common_terms=simple_terms_for_category(category))

    return CleanDecision("uncertain", 0.50, "needs_reasoning_cleanup", normalized_title=normalized, normalized_category=canonical.category, common_terms=simple_terms_for_category(category))
