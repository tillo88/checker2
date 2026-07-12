from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Any

from .catalog import analysis_to_jsonable
from .models import HarvestListing
from .variant_dimensions import analyze_listing_product
from .validator import validate_product_analysis


@dataclass(frozen=True)
class ClassifiedListing:
    listing: HarvestListing
    analysis: dict[str, Any]
    warnings: tuple[str, ...] = ()


def classify_listing(listing: HarvestListing) -> ClassifiedListing:
    text = " ".join(
        str(x or "")
        for x in [
            listing.title,
            listing.category,
            listing.raw.get("text") if isinstance(listing.raw, dict) else "",
        ]
    )
    analysis = analyze_listing_product(text)
    warnings = tuple(validate_product_analysis(text, analysis))
    return ClassifiedListing(listing, analysis_to_jsonable(analysis), warnings)


def classify_batch(listings: Iterable[HarvestListing], *, batch_size: int = 50) -> list[ClassifiedListing]:
    out: list[ClassifiedListing] = []
    batch: list[HarvestListing] = []
    for listing in listings:
        batch.append(listing)
        if len(batch) >= batch_size:
            out.extend(classify_listing(x) for x in batch)
            batch = []
    if batch:
        out.extend(classify_listing(x) for x in batch)
    return out


def summarize_classification(items: Iterable[ClassifiedListing]) -> dict[str, Any]:
    total = 0
    categories: dict[str, int] = {}
    ambiguous = 0
    warnings = 0
    for item in items:
        total += 1
        cat = item.analysis.get("category") or "unknown"
        categories[cat] = categories.get(cat, 0) + 1
        if item.analysis.get("ambiguity_status") != "resolved":
            ambiguous += 1
        if item.warnings:
            warnings += len(item.warnings)
    return {
        "total": total,
        "categories": categories,
        "ambiguous": ambiguous,
        "warnings": warnings,
    }
