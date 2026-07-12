from __future__ import annotations

from .models import SourceDefinition


# Conservative registry:
# - enabled = public catalog/refurbished pages where generic HTML/JSON-LD parsing is plausible
# - experimental = classifieds/search pages needing live validation and low rate
# - manual/disabled = no automated collection in this patch
SOURCES: dict[str, SourceDefinition] = {
    "amazon": SourceDefinition(
        name="amazon",
        label="Amazon",
        group="retail_catalog_api_preferred",
        countries=("EU", "IT", "DE", "FR", "ES", "NL", "UK", "US"),
        status="manual",
        default_enabled=False,
        requires_login=False,
        search_url_templates=(),
        notes=(
            "Use official API/import path only. Do not HTML-crawl Amazon search/product pages. "
            "Good source for ASIN, variation dimensions, EAN/GTIN and catalog facts when credentials/terms allow it."
        ),
    ),

    "backmarket": SourceDefinition(
        name="backmarket",
        label="Back Market",
        group="refurbished_electronics",
        countries=("EU", "IT", "DE", "FR", "ES", "NL", "US"),
        status="experimental",
        default_enabled=False,
        search_url_templates=(
            "https://www.backmarket.it/it-it/search?q={query}",
            "https://www.backmarket.de/de-de/search?q={query}",
            "https://www.backmarket.fr/fr-fr/search?q={query}",
        ),
        notes="Refurbished electronics catalog. Enable explicitly until selectors/robots are verified.",
    ),
    "refurbed": SourceDefinition(
        name="refurbed",
        label="refurbed",
        group="refurbished_electronics",
        countries=("EU", "IT", "DE", "AT", "NL", "IE"),
        status="experimental",
        default_enabled=False,
        search_url_templates=(
            "https://www.refurbed.it/search/?query={query}",
            "https://www.refurbed.de/search/?query={query}",
            "https://www.refurbed.nl/en-nl/search/?query={query}",
        ),
        notes="Refurbished electronics catalog. Enable explicitly until selectors/robots are verified.",
    ),
    "swappie": SourceDefinition(
        name="swappie",
        label="Swappie",
        group="refurbished_electronics",
        countries=("EU", "DE", "IT", "FI", "SE"),
        status="experimental",
        default_enabled=False,
        search_url_templates=(
            "https://swappie.com/it/search/?q={query}",
            "https://swappie.com/de-en/search/?q={query}",
        ),
        notes="Mainly refurbished Apple devices; experimental generic HTML collector.",
    ),
    "rebuy": SourceDefinition(
        name="rebuy",
        label="reBuy",
        group="refurbished_electronics",
        countries=("DE", "AT", "FR", "NL", "IT", "ES"),
        status="experimental",
        default_enabled=False,
        search_url_templates=(
            "https://www.rebuy.de/kaufen/suchen?q={query}",
            "https://www.rebuy.fr/acheter/recherche?q={query}",
        ),
        notes="Recommerce electronics/media; experimental generic HTML collector.",
    ),
    "cex": SourceDefinition(
        name="cex",
        label="CeX",
        group="used_electronics",
        countries=("EU", "IT", "ES", "PT", "IE", "UK"),
        status="experimental",
        default_enabled=False,
        search_url_templates=(
            "https://it.webuy.com/search?stext={query}",
            "https://es.webuy.com/search?stext={query}",
            "https://pt.webuy.com/search?stext={query}",
        ),
        notes="Used electronics retailer; experimental generic HTML collector.",
    ),

    # Existing bot families / broad classifieds. These remain experimental here:
    # SpyEngine already has runtime adapters; the nightly cache will get
    # source-specific collectors later.
    "vinted": SourceDefinition(
        name="vinted",
        label="Vinted",
        group="classifieds_second_hand",
        countries=("EU",),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://www.vinted.it/catalog?search_text={query}",),
        notes="Existing SpyEngine platform; nightly HTML collector is experimental.",
    ),
    "subito": SourceDefinition(
        name="subito",
        label="Subito",
        group="classifieds_second_hand",
        countries=("IT",),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://www.subito.it/annunci-italia/vendita/usato/?q={query}",),
        notes="Existing SpyEngine platform; nightly HTML collector is experimental.",
    ),
    "wallapop": SourceDefinition(
        name="wallapop",
        label="Wallapop",
        group="classifieds_second_hand",
        countries=("ES", "IT", "PT"),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://es.wallapop.com/app/search?keywords={query}",),
        notes="Existing SpyEngine platform; nightly HTML collector is experimental.",
    ),
    "ebay": SourceDefinition(
        name="ebay",
        label="eBay",
        group="marketplace_api_preferred",
        countries=("EU",),
        status="manual",
        default_enabled=False,
        search_url_templates=("https://www.ebay.it/sch/i.html?_nkw={query}",),
        notes="Prefer official Browse API/runtime adapter. HTML collector disabled by default.",
    ),
    "kleinanzeigen": SourceDefinition(
        name="kleinanzeigen",
        label="Kleinanzeigen",
        group="classifieds_second_hand",
        countries=("DE",),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://www.kleinanzeigen.de/s-suchanfrage.html?keywords={query}",),
        notes="German classifieds; enable only after robots/selector validation.",
    ),
    "leboncoin": SourceDefinition(
        name="leboncoin",
        label="Leboncoin",
        group="classifieds_second_hand",
        countries=("FR",),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://www.leboncoin.fr/recherche?text={query}",),
        notes="French classifieds; enable only after robots/selector validation.",
    ),
    "marktplaats": SourceDefinition(
        name="marktplaats",
        label="Marktplaats",
        group="classifieds_second_hand",
        countries=("NL",),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://www.marktplaats.nl/l/q/{query}/",),
        notes="Dutch classifieds; enable only after robots/selector validation.",
    ),
    "2dehands": SourceDefinition(
        name="2dehands",
        label="2dehands / 2ememain",
        group="classifieds_second_hand",
        countries=("BE",),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://www.2dehands.be/q/{query}/",),
        notes="Belgian classifieds; enable only after robots/selector validation.",
    ),
    "willhaben": SourceDefinition(
        name="willhaben",
        label="willhaben",
        group="classifieds_second_hand",
        countries=("AT",),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz?keyword={query}",),
        notes="Austrian classifieds; enable only after robots/selector validation.",
    ),
    "tutti": SourceDefinition(
        name="tutti",
        label="tutti.ch",
        group="classifieds_second_hand",
        countries=("CH",),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://www.tutti.ch/it/q/{query}",),
        notes="Swiss classifieds; enable only after robots/selector validation.",
    ),
    "ricardo": SourceDefinition(
        name="ricardo",
        label="Ricardo",
        group="marketplace_second_hand",
        countries=("CH",),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://www.ricardo.ch/it/s/{query}/",),
        notes="Swiss auction/marketplace; enable only after robots/selector validation.",
    ),
    "olx_pl": SourceDefinition(
        name="olx_pl",
        label="OLX Poland",
        group="classifieds_second_hand",
        countries=("PL",),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://www.olx.pl/oferty/q-{query}/",),
        notes="Polish classifieds; enable only after robots/selector validation.",
    ),
    "bazos": SourceDefinition(
        name="bazos",
        label="Bazoš",
        group="classifieds_second_hand",
        countries=("CZ", "SK"),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://www.bazos.cz/search.php?hledat={query}",),
        notes="Czech/Slovak classifieds; enable only after robots/selector validation.",
    ),
    "blocket": SourceDefinition(
        name="blocket",
        label="Blocket",
        group="classifieds_second_hand",
        countries=("SE",),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://www.blocket.se/annonser/hela_sverige?q={query}",),
        notes="Swedish classifieds; enable only after robots/selector validation.",
    ),
    "dba": SourceDefinition(
        name="dba",
        label="DBA",
        group="classifieds_second_hand",
        countries=("DK",),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://www.dba.dk/soeg/?soeg={query}",),
        notes="Danish classifieds; enable only after robots/selector validation.",
    ),
    "tori": SourceDefinition(
        name="tori",
        label="Tori",
        group="classifieds_second_hand",
        countries=("FI",),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://www.tori.fi/recommerce/forsale/search?query={query}",),
        notes="Finnish classifieds; enable only after robots/selector validation.",
    ),
    "finn": SourceDefinition(
        name="finn",
        label="FINN.no",
        group="classifieds_second_hand",
        countries=("NO",),
        status="experimental",
        default_enabled=False,
        search_url_templates=("https://www.finn.no/bap/forsale/search.html?q={query}",),
        notes="Norwegian classifieds; enable only after robots/selector validation.",
    ),

    "facebook_marketplace": SourceDefinition(
        name="facebook_marketplace",
        label="Facebook Marketplace",
        group="manual_or_permission_required",
        countries=("EU",),
        status="disabled",
        default_enabled=False,
        requires_login=True,
        search_url_templates=(),
        notes=(
            "No automatic scraping in this patch. Use only permissioned/manual import paths; "
            "do not bypass login, rate limits, anti-bot, or privacy controls."
        ),
    ),
}


def list_sources(*, include_experimental: bool = True, include_disabled: bool = False) -> list[SourceDefinition]:
    out: list[SourceDefinition] = []
    for src in SOURCES.values():
        if src.status == "disabled" and not include_disabled:
            continue
        if src.status == "experimental" and not include_experimental:
            continue
        out.append(src)
    return sorted(out, key=lambda s: (s.group, s.name))


def source_names(*, include_experimental: bool = True, include_disabled: bool = False) -> list[str]:
    return [s.name for s in list_sources(include_experimental=include_experimental, include_disabled=include_disabled)]


def get_source(name: str) -> SourceDefinition:
    key = name.strip().lower()
    if key not in SOURCES:
        raise KeyError(f"Unknown marketplace source: {name}")
    return SOURCES[key]


def default_source_names() -> list[str]:
    return [s.name for s in SOURCES.values() if s.default_enabled]
