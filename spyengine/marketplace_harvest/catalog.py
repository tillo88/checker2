from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json
import re

from .models import HarvestListing
from .variant_dimensions import analyze_listing_product, normalize_text_key
from .canonicalize import canonicalize_title, canonical_category_from_title
from .identifiers import extract_product_identifiers
from .category_schema import category_keys


@dataclass(frozen=True)
class CatalogResolution:
    family_id: int | None
    variant_id: int | None
    analysis: dict[str, Any]


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()

_VALID_CATEGORY_KEYS = set(category_keys())
_CATEGORY_ALIASES = {
    "technology_phone": "technology_smartphone",
    "technology_storage_ssd": "technology_storage",
    "technology_storage_hdd": "technology_storage",
}
_ICON_NOISE_RE = re.compile(
    r"\s*,\s*(?:ikon|icon|kuvake|icona|ikona)\s+(?:av|af|of|di|de|för|for).*$",
    re.I,
)


def _valid_category_key(value: Any) -> str:
    raw = _clean_text(value)
    if not raw or raw.lower() in {"unknown", "none", "null", "vehicle_car_weak"}:
        return ""
    raw = _CATEGORY_ALIASES.get(raw, raw)
    if raw in _VALID_CATEGORY_KEYS:
        return raw

    # Strip marketplace UI/accessibility suffixes like
    # "Möbler och inredning , Ikon av" / "Møbler og indretning , Ikon af".
    simplified = _ICON_NOISE_RE.sub("", raw).strip()
    simplified = _CATEGORY_ALIASES.get(simplified, simplified)
    if simplified in _VALID_CATEGORY_KEYS:
        return simplified

    # Try both as source-category fallback and as free text.  Only accept if the
    # result is a known canonical key; never keep raw UI labels in the catalog.
    for candidate in (canonical_category_from_title("", simplified), canonical_category_from_title(simplified, "")):
        candidate = _CATEGORY_ALIASES.get(_clean_text(candidate), _clean_text(candidate))
        if candidate in _VALID_CATEGORY_KEYS and candidate != "unknown":
            return candidate
    return ""


def _meaningful_category(value: Any) -> str:
    return _valid_category_key(value)


def _json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        try:
            decoded = json.loads(str(value))
            raw = decoded if isinstance(decoded, list) else []
        except Exception:
            raw = []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = _clean_text(item)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _raw_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw or "{}"))
    except Exception:
        return {}


def _evidence_confidence(raw: dict[str, Any], fallback: float = 0.5) -> float:
    ev = raw.get("promoted_evidence") if isinstance(raw.get("promoted_evidence"), dict) else {}
    candidates = [fallback]
    for key in ("selected_confidence", "ai_edge_confidence", "research_confidence", "multilingual_confidence", "verify_confidence"):
        try:
            candidates.append(float(ev.get(key)))
        except Exception:
            pass
    return max([c for c in candidates if c is not None] or [fallback])


def _family_name_from_evidence(title: str, category: str, brand: str = "", model: str = "") -> str:
    clean = canonicalize_title(title)
    brand = _clean_text(brand)
    model = _clean_text(model)
    if brand and model:
        combined = f"{brand} {model}".strip()
        if combined.casefold() not in clean.casefold():
            return combined[:96]
    if model and model.casefold() not in clean.casefold() and len(clean) < 12:
        return f"{clean} {model}".strip()[:96]
    return clean[:96]


def _merge_aliases(*values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, str):
            candidates = [value]
        else:
            candidates = _json_list(value)
        for item in candidates:
            text = _clean_text(item)
            if len(text) < 2:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
    return out[:32]


def upsert_catalog_from_listing(store, listing: HarvestListing, *, listing_id: int | None = None) -> CatalogResolution:
    """Learn/update catalog rows from a listing using the strongest evidence already stored.

    Older catalog learning inferred identity from title-only, which was OK for early tech-only
    GPU/RAM work but too lossy for general marketplace evidence.  M9.7.12 makes the catalog
    learner evidence-aware: cleaned/verified AI/Vision and online-research category hints are
    allowed to seed product families, variants and aliases instead of being discarded.
    """
    identity_text = _clean_text(listing.title)
    if not identity_text:
        return CatalogResolution(None, None, {"reason": "empty_title"})

    raw = _raw_dict(getattr(listing, "raw", {}) or {})
    category_hint = _meaningful_category(getattr(listing, "category", ""))
    brand_hint = _clean_text(raw.get("promoted_brand") or raw.get("canonical_brand") or raw.get("brand"))
    model_hint = _clean_text(raw.get("promoted_model") or raw.get("canonical_model") or raw.get("model"))
    aliases_hint = _merge_aliases(raw.get("promoted_aliases"), raw.get("aliases"), identity_text)

    # Start with the old analyzer so GPU/RAM/monitor identifiers/spec extraction keep working.
    analysis = analyze_listing_product(identity_text)
    old_category = _meaningful_category(analysis.get("category")) or "unknown"
    analysis["category_before_evidence_hint"] = analysis.get("category") or "unknown"
    analysis["category"] = old_category

    if category_hint:
        # Evidence from clean/research/vision should win over title-only unknown or stale tech-only guesses.
        if old_category == "unknown" or category_hint != old_category:
            analysis["category"] = category_hint

    category = _meaningful_category(analysis.get("category")) or category_hint or "unknown"
    brand = brand_hint or _clean_text(analysis.get("brand"))
    model = model_hint
    family_name = _clean_text(analysis.get("family_name"))
    if not family_name or family_name.lower() == "unknown":
        family_name = _family_name_from_evidence(identity_text, category, brand, model)
    if not family_name:
        return CatalogResolution(None, None, {**analysis, "reason": "empty_family_name_after_learning"})

    confidence = max(float(analysis.get("confidence") or 0.35), _evidence_confidence(raw, 0.5))
    family_key = f"{category}:{normalize_text_key(brand) or 'unknown'}:{normalize_text_key(family_name)}"
    variant_specs = dict(analysis.get("variant_specs") or {})
    identifiers = list(analysis.get("identifiers") or [])
    if model:
        identifiers.extend(extract_product_identifiers(model))

    metadata = {
        "source": listing.source,
        "query": listing.query,
        "learning_source": (raw.get("promoted_evidence") or {}).get("title_category_source", "listing"),
        "evidence": raw.get("promoted_evidence") or {},
        "category_hint": category_hint,
        "brand_hint": brand_hint,
        "model_hint": model_hint,
        "ambiguity_status": analysis.get("ambiguity_status"),
    }
    family_id = store.upsert_product_family(
        category=category,
        brand=brand,
        family_name=family_name,
        family_key=family_key,
        confidence=confidence,
        metadata=metadata,
    )

    variant_id = None
    should_create_variant = bool(variant_specs or identifiers or model)
    if should_create_variant:
        variant_name = _clean_text(model and f"{brand} {model}" or analysis.get("variant_name") or family_name)
        variant_key_base = analysis.get("variant_key") or family_key
        if model:
            variant_key = f"{category}:{normalize_text_key(brand) or 'unknown'}:{normalize_text_key(model)}"
        else:
            variant_key = str(variant_key_base)
        variant_id = store.upsert_product_variant(
            family_id=family_id,
            variant_key=variant_key,
            variant_name=variant_name,
            variant_label=variant_name,
            confidence=confidence,
            ambiguity_status=analysis.get("ambiguity_status") or "resolved",
            metadata=metadata,
        )
        for key, value in variant_specs.items():
            store.upsert_spec_fact(
                variant_id=variant_id,
                family_id=family_id,
                spec_key=key,
                spec_value=value,
                unit=_guess_unit(key),
                source=listing.source,
                confidence=min(0.95, confidence),
            )
        for ident in identifiers:
            try:
                store.upsert_product_identifier(
                    variant_id=variant_id,
                    family_id=family_id,
                    identifier_type=getattr(ident, "identifier_type", "identifier"),
                    identifier_value=getattr(ident, "value", str(ident)),
                    source=getattr(ident, "source", listing.source),
                    confidence=float(getattr(ident, "confidence", min(0.95, confidence))),
                )
            except Exception:
                pass
        if listing_id is not None:
            store.link_listing_variant_candidate(
                listing_id=listing_id,
                variant_id=variant_id,
                score=confidence,
                reason=metadata["learning_source"] or "evidence_catalog_learning",
            )
    elif listing_id is not None:
        store.link_listing_family_candidate(
            listing_id=listing_id,
            family_id=family_id,
            score=confidence,
            reason=metadata["learning_source"] or "evidence_family_learning",
        )

    for alias in _merge_aliases(aliases_hint, family_name, model and f"{brand} {model}"):
        try:
            store.upsert_product_alias(
                family_id=family_id,
                variant_id=variant_id,
                alias=alias,
                source=metadata["learning_source"] or listing.source,
                confidence=min(0.95, confidence),
            )
        except Exception:
            pass

    final_analysis = dict(analysis)
    final_analysis.update({
        "category": category,
        "brand": brand,
        "model": model,
        "family_name": family_name,
        "family_key": family_key,
        "variant_key": variant_id and (model and f"{category}:{normalize_text_key(brand) or 'unknown'}:{normalize_text_key(model)}" or analysis.get("variant_key")),
        "aliases": aliases_hint,
        "confidence": confidence,
        "learning_source": metadata["learning_source"],
    })
    return CatalogResolution(family_id, variant_id, final_analysis)


def _guess_unit(key: str) -> str:
    key = key.lower()
    if key.endswith("_gb") or key in {"vram_gb", "module_capacity_gb", "kit_total_gb"}: return "GB"
    if key.endswith("_hz") or key == "refresh_hz": return "Hz"
    if key.endswith("_inches") or key == "size_inches": return "inch"
    return ""


def analysis_to_jsonable(analysis: dict[str, Any]) -> dict[str, Any]:
    out = dict(analysis)
    if "identifiers" in out:
        out["identifiers"] = [
            {
                "identifier_type": getattr(i, "identifier_type", ""),
                "value": getattr(i, "value", ""),
                "confidence": getattr(i, "confidence", 0.0),
                "source": getattr(i, "source", ""),
            }
            if not isinstance(i, dict) else i
            for i in out["identifiers"]
        ]
    return out
