from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from .registry import get_source, list_sources


@dataclass(frozen=True)
class SourceMarketPolicy:
    source: str
    label: str
    group: str
    countries: tuple[str, ...]
    market_country: str
    scope: str
    italy_deal_candidate: bool
    catalog_candidate: bool
    needs_shipping_check: bool
    reason: str


def _host_country_hint(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.endswith(".it"):
        return "IT"
    if host.endswith(".de"):
        return "DE"
    if host.endswith(".fr"):
        return "FR"
    if host.endswith(".es"):
        return "ES"
    if host.endswith(".nl"):
        return "NL"
    if host.endswith(".be"):
        return "BE"
    if host.endswith(".at"):
        return "AT"
    if host.endswith(".ch"):
        return "CH"
    if host.endswith(".pl"):
        return "PL"
    if host.endswith(".cz"):
        return "CZ"
    if host.endswith(".se"):
        return "SE"
    if host.endswith(".dk"):
        return "DK"
    if host.endswith(".fi"):
        return "FI"
    if host.endswith(".no"):
        return "NO"
    return ""


def source_country_hints(source_name: str) -> set[str]:
    src = get_source(source_name)
    hints = {str(c).upper() for c in src.countries}
    for tpl in src.search_url_templates:
        # Templates contain {query}; replace with harmless text to parse URL.
        try:
            url = tpl.format(query="test", q="test", raw_query="test", limit=1)
        except Exception:
            url = tpl
        hint = _host_country_hint(url)
        if hint:
            hints.add(hint)
    return hints


def classify_source_for_market(source_name: str, *, market_country: str = "IT") -> SourceMarketPolicy:
    """Classify a source for the target market.

    This is intentionally conservative. It does not claim that a site currently
    ships to Italy; it decides whether the source is a good candidate for:
    - local/Italy deal monitoring
    - catalog/reference data only
    - manual shipping-policy verification

    Live shipping policy should still be verified per source when we promote a
    source from catalog-only/experimental into production deal alerts.
    """

    src = get_source(source_name)
    mc = (market_country or "IT").upper()
    countries = source_country_hints(source_name)
    group = src.group.lower()

    is_classifieds = "classifieds" in group or "second_hand" in group or "marketplace_second_hand" in group
    is_retailish = (
        "refurbished" in group
        or "used_electronics" in group
        or "retail" in group
        or "recommerce" in group
        or "catalog" in group
    )

    if mc in countries:
        if is_classifieds:
            scope = "target_market_classifieds_candidate"
            reason = f"{source_name} has {mc} in registry/URL hints; usable for deal smoke, still validate shipping/pickup semantics."
            return SourceMarketPolicy(src.name, src.label, src.group, tuple(sorted(countries)), mc, scope, True, True, True, reason)
        scope = "target_market_retail_or_catalog_candidate"
        reason = f"{source_name} has {mc} in registry/URL hints; good candidate for catalog/deal checks, verify shipping policy before alerts."
        return SourceMarketPolicy(src.name, src.label, src.group, tuple(sorted(countries)), mc, scope, True, True, True, reason)

    if "EU" in countries and is_retailish:
        scope = "eu_retail_catalog_needs_shipping_check"
        reason = f"{source_name} is EU/retail-like but no explicit {mc} hint; keep catalog-capable, require shipping check for deals."
        return SourceMarketPolicy(src.name, src.label, src.group, tuple(sorted(countries)), mc, scope, False, True, True, reason)

    if is_classifieds:
        scope = "foreign_classifieds_catalog_only"
        reason = f"{source_name} looks like foreign classifieds for {tuple(sorted(countries))}; useful for catalog/prices, not default {mc} deal alerts."
        return SourceMarketPolicy(src.name, src.label, src.group, tuple(sorted(countries)), mc, scope, False, True, False, reason)

    scope = "unknown_manual_review"
    reason = f"{source_name} has no confident {mc} shipping/deal signal; manual review needed."
    return SourceMarketPolicy(src.name, src.label, src.group, tuple(sorted(countries)), mc, scope, False, False, True, reason)


def classify_sources_for_market(source_names: list[str] | None = None, *, market_country: str = "IT") -> dict[str, dict]:
    names = source_names or [s.name for s in list_sources(include_experimental=True, include_disabled=False)]
    out: dict[str, dict] = {}
    for name in names:
        try:
            out[name] = asdict(classify_source_for_market(name, market_country=market_country))
        except Exception as e:
            out[name] = {
                "source": name,
                "market_country": market_country,
                "scope": "policy_error",
                "italy_deal_candidate": False,
                "catalog_candidate": False,
                "needs_shipping_check": True,
                "reason": repr(e),
            }
    return out
