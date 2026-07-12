"""Nightly marketplace harvesting foundation for SpyEngine."""

from .models import HarvestListing, SourceDefinition
from .registry import get_source, list_sources, source_names
from .store import MarketplaceCacheStore

__all__ = [
    "HarvestListing",
    "SourceDefinition",
    "MarketplaceCacheStore",
    "get_source",
    "list_sources",
    "source_names",
]

from .identifiers import extract_product_identifiers
from .variant_dimensions import analyze_listing_product
from .classifier import classify_batch, classify_listing
from .fact_checker import authoritative_sources_for, check_variant_conflicts
from .adapters import build_category_crawl_plan
