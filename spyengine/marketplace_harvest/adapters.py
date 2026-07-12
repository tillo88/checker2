from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote_plus

from .category_schema import DEFAULT_CATEGORY_NODES, broad_queries_for_category
from .registry import get_source, list_sources


@dataclass(frozen=True)
class CrawlTask:
    source: str
    mode: str
    category_key: str
    category_label: str
    query: str
    url: str
    page: int = 1


@dataclass(frozen=True)
class SourceAdapterSpec:
    source: str
    mode: str = "search_templates"
    supports_categories: bool = True
    stable: bool = False
    notes: str = ""


class MarketplaceAdapter:
    def __init__(self, source_name: str):
        self.source = get_source(source_name)
        self.spec = ADAPTER_SPECS.get(source_name, SourceAdapterSpec(source=source_name))

    def category_tasks(
        self,
        *,
        category_keys: Iterable[str] | None = None,
        top_n: int = 100,
        max_pages: int = 1,
    ) -> list[CrawlTask]:
        keys = set(category_keys or [c.key for c in DEFAULT_CATEGORY_NODES if c.key != "unknown"])
        tasks: list[CrawlTask] = []
        for node in DEFAULT_CATEGORY_NODES:
            if node.key not in keys or node.key == "unknown":
                continue
            queries = broad_queries_for_category(node.key, max_queries=6)
            for query in queries:
                for url in self.source.build_urls(query, limit=top_n):
                    tasks.append(
                        CrawlTask(
                            source=self.source.name,
                            mode="broad_category_query",
                            category_key=node.key,
                            category_label=node.label,
                            query=query,
                            url=url,
                            page=1,
                        )
                    )
        return tasks

    def search_tasks(self, queries: Iterable[str], *, top_n: int = 100) -> list[CrawlTask]:
        tasks: list[CrawlTask] = []
        for query in queries:
            for url in self.source.build_urls(query, limit=top_n):
                tasks.append(CrawlTask(self.source.name, "search", "unknown", "Sconosciuto", query, url))
        return tasks


ADAPTER_SPECS: dict[str, SourceAdapterSpec] = {
    "ebay": SourceAdapterSpec("ebay", mode="api_preferred", stable=True, notes="Preferire Browse API; HTML solo manual/diagnostica."),
    "subito": SourceAdapterSpec("subito", stable=True, notes="Adapter runtime esistente; category harvester usa query larghe."),
    "vinted": SourceAdapterSpec("vinted", stable=True, notes="Adapter runtime esistente; category harvester usa query larghe."),
    "wallapop": SourceAdapterSpec("wallapop", stable=True, notes="Adapter runtime esistente; category harvester usa query larghe."),
    "backmarket": SourceAdapterSpec("backmarket", mode="refurbished_html", notes="Catalogo refurbished sperimentale."),
    "refurbed": SourceAdapterSpec("refurbed", mode="refurbished_html", notes="Catalogo refurbished sperimentale."),
    "swappie": SourceAdapterSpec("swappie", mode="refurbished_html", notes="Apple refurbished sperimentale."),
    "rebuy": SourceAdapterSpec("rebuy", mode="refurbished_html", notes="Recommerce sperimentale."),
    "cex": SourceAdapterSpec("cex", mode="retail_used_html", notes="Used electronics retailer sperimentale."),
}


def available_adapters(*, include_experimental: bool = True) -> list[str]:
    names = []
    for src in list_sources(include_experimental=include_experimental, include_disabled=False):
        if src.status == "disabled" or src.requires_login:
            continue
        # Manual/API-only sources stay in registry but not automatic category crawling.
        if src.status == "manual":
            continue
        names.append(src.name)
    return names


def build_category_crawl_plan(
    *,
    sources: Iterable[str] | None = None,
    category_keys: Iterable[str] | None = None,
    top_n: int = 100,
    max_pages: int = 1,
    include_experimental: bool = True,
) -> list[CrawlTask]:
    source_names = list(sources or available_adapters(include_experimental=include_experimental))
    tasks: list[CrawlTask] = []
    for source_name in source_names:
        adapter = MarketplaceAdapter(source_name)
        tasks.extend(adapter.category_tasks(category_keys=category_keys, top_n=top_n, max_pages=max_pages))
    # Dedup by URL/query/category/source.
    seen: set[tuple[str, str, str, str]] = set()
    out: list[CrawlTask] = []
    for task in tasks:
        key = (task.source, task.category_key, task.query.lower(), task.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(task)
    return out


# ==================== SITE-NATIVE CATEGORY DISCOVERY ====================

from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qsl, urlunparse
import os
import re


@dataclass(frozen=True)
class SiteCategory:
    """A category discovered from the marketplace site's own navigation."""

    source: str
    label: str
    url: str
    path: tuple[str, ...] = ()
    depth: int = 0
    parent_url: str = ""

    @property
    def path_label(self) -> str:
        return " > ".join(self.path or (self.label,))


SOURCE_ENTRYPOINTS: dict[str, tuple[str, ...]] = {
    "subito": ("https://www.subito.it/",),
    "vinted": ("https://www.vinted.it/",),
    "wallapop": ("https://es.wallapop.com/",),
    "backmarket": ("https://www.backmarket.it/it-it", "https://www.backmarket.de/de-de", "https://www.backmarket.fr/fr-fr"),
    "refurbed": ("https://www.refurbed.it/", "https://www.refurbed.de/", "https://www.refurbed.nl/en-nl/"),
    "swappie": ("https://swappie.com/it/", "https://swappie.com/de-en/"),
    "rebuy": ("https://www.rebuy.de/", "https://www.rebuy.fr/"),
    "cex": ("https://it.webuy.com/", "https://es.webuy.com/", "https://pt.webuy.com/"),
    "kleinanzeigen": ("https://www.kleinanzeigen.de/",),
    "leboncoin": ("https://www.leboncoin.fr/",),
    "marktplaats": ("https://www.marktplaats.nl/",),
    "2dehands": ("https://www.2dehands.be/",),
    "willhaben": ("https://www.willhaben.at/",),
    "tutti": ("https://www.tutti.ch/it",),
    "ricardo": ("https://www.ricardo.ch/it/",),
    "olx_pl": ("https://www.olx.pl/",),
    "bazos": ("https://www.bazos.cz/",),
    "blocket": ("https://www.blocket.se/",),
    "dba": ("https://www.dba.dk/",),
    "tori": ("https://www.tori.fi/",),
    "finn": ("https://www.finn.no/",),
}


_SKIP_LINK_RE = re.compile(
    r"(login|signin|signup|registr|account|profil|messag|chat|help|aiuto|privacy|cookie|terms|condizioni|"
    r"cart|carrello|checkout|sell|vendi|publish|inserisci|post-ad|advertis|business|about|contatti|"
    r"download|app-store|google-play|facebook|instagram|tiktok|youtube|linkedin|twitter|x\.com|upload|napov|nápov|dotazy|hodnocen|faq|ayuda)",
    re.I,
)


_LANGUAGE_SWITCH_RE = re.compile(
    r"^(it|en|de|fr|es|pt|nl|be|ch|at|pl|cz|se|dk|fi|no|en nl|nl en|de de|fr fr|it it|es es)$",
    re.I,
)

_GENERIC_CATEGORY_NAV_RE = re.compile(
    r"^(all categories|view all|show all|tutte le categorie|tutto|tutti|categories|categorie|menu|home|homepage)$",
    re.I,
)

_GENERIC_DEAL_RE = re.compile(
    r"^(deals?|offerte|promozioni|apple weeks|black friday|sale|sconti)$",
    re.I,
)


_TECH_CATEGORY_POSITIVE_RE = re.compile(
    r"(elettronica|electronics|elektronik|elektroniikka|electr[oó]nica|informatica|computer|computers|"
    r"pc\b|laptop|notebook|portatil|portatili|macbook|thinkpad|tablet|ipad|iphone|smartphone|telefono|"
    r"telefoni|telefoner|cellular|samsung|apple|console|playstation|xbox|nintendo|steam\s*deck|gpu|"
    r"scheda\s*video|rtx|radeon|quadro|audio|cuffie|headphones|auricolari|airpods|kamera|camera|"
    r"fotografia|foto|versterkers|receivers|ontvangers|televisies|vitvaror|witgoed|hvidevarer|kodinkoneet)",
    re.I,
)

_TECH_CATEGORY_STRONG_RE = re.compile(
    r"(elettronica|electronics|elektronik|elektroniikka|informatica|computer|laptop|notebook|"
    r"tablet|ipad|iphone|smartphone|telefon|telefoni|telefoner|cellular|console|playstation|xbox|"
    r"gpu|rtx|radeon|audio|cuffie|airpods|versterkers|receivers|ontvangers)",
    re.I,
)

_CATEGORY_NEGATIVE_RE = re.compile(
    r"(auto'?s|auto\b|moto\b|motor|boot\b|boat|immobili|immobilier|immo\b|real\s*estate|huis|casa\b|"
    r"home|koti|mobili|möbler|møbler|furniture|inredning|indretning|sisustus|abbigliamento|fashion|"
    r"moda|klær|kleidung|vaatteet|vestiti|scarpe|sport|giardino|garden|bricolage|bambini|jobs?|lavoro|"
    r"zwierzęta|zwierzeta|zdrowie|uroda|firma|przemysł|przemysl|budowa|remont|"
    r"help|aiuto|hilfe|napov|nápov|dotazy|hodnocen|faq|privacy|cookie|upload|compra\s+y\s+vende|"
    r"alle\s+anzeigen|s-kategorien|marktplatz\s+\d|antyki|kolekcje|antiques?)",
    re.I,
)

_CATEGORY_HARD_NOISE_RE = re.compile(
    r"(help|aiuto|hilfe|napov|nápov|dotazy|hodnocen|faq|privacy|cookie|terms|condizioni|upload|"
    r"login|registr|account|profil|messag|chat|contatti|kontakt|about|advertis|reklama|business|"
    r"download|app-store|google-play|rss\b|podm[ií]nky|ochrana|udaj|údaj|nejvyhled|mapa-search|"
    r"mapa-kategorie|mapa\s+kategori|terms|conditions|gdpr|datenschutz)",
    re.I,
)

_CATEGORY_PROFILE_ENV = "SPYENGINE_CATEGORY_PROFILE"
_CATEGORY_PROFILES = {"tech", "general", "all"}


def normalize_category_profile(profile: str | None = None) -> str:
    value = (profile or os.getenv(_CATEGORY_PROFILE_ENV) or "tech").strip().lower()
    return value if value in _CATEGORY_PROFILES else "tech"


def category_profile_label(profile: str | None = None) -> str:
    return normalize_category_profile(profile)



def category_interest_score(
    source_name: str,
    label: str,
    url: str = "",
    path: tuple[str, ...] = (),
    *,
    profile: str | None = None,
) -> int:
    """Score category usefulness for the selected category profile.

    Profiles:
    - tech: prioritize hardware/electronics and strongly demote unrelated areas
    - general: still prefers useful product categories, but demotes unrelated areas mildly
    - all: keeps discovery broad; only hard-noise links should be filtered elsewhere

    The score is used for ordering, not as a hard production truth.
    """

    profile = normalize_category_profile(profile)
    hay = " ".join([source_name or "", label or "", url or "", " ".join(path or ())]).lower()
    score = 0

    if _TECH_CATEGORY_POSITIVE_RE.search(hay):
        score += 30
    if _TECH_CATEGORY_STRONG_RE.search(hay):
        score += 25
    if re.search(r"(/c/(smartphone|computer|tablet|cuffie|iphone|ipad|macbook)|/electronics|/elektronik|category=.*(electronics|elektronik))", hay, re.I):
        score += 20
    if re.search(r"\b(apple|samsung|sony|dell|lenovo|hp|nvidia|amd)\b", hay, re.I):
        score += 8

    if _CATEGORY_HARD_NOISE_RE.search(hay):
        score -= 120

    negative = bool(_CATEGORY_NEGATIVE_RE.search(hay))
    if negative:
        if profile == "tech":
            score -= 35
        elif profile == "general":
            score -= 10
        elif profile == "all":
            score -= 0

    # Source-specific hints from smoke reports.
    if profile == "tech":
        if source_name in {"marktplaats", "2dehands", "kleinanzeigen", "willhaben"} and re.search(r"\b(auto|immo|immobili|motor|boot)\b", hay, re.I):
            score -= 30
        if source_name in {"blocket", "dba", "tori", "finn"} and re.search(r"\b(möbler|møbler|koti|sisustus|klær|vaatteet|fashion|mote)\b", hay, re.I):
            score -= 25
        if source_name == "wallapop" and re.search(r"\b(moto|honda|cbr|upload|compra\s+y\s+vende)\b", hay, re.I):
            score -= 40
        if source_name == "bazos" and re.search(r"\b(nápověda|napoveda|dotazy|hodnocení|hodnoceni|rss|reklama|podm[ií]nky|kontakt)\b", hay, re.I):
            score -= 80

    return int(score)



def sort_site_categories_for_target(
    source_name: str,
    categories: list["SiteCategory"],
    *,
    profile: str | None = None,
) -> list["SiteCategory"]:
    profile = normalize_category_profile(profile)
    return sorted(
        categories,
        key=lambda c: (
            category_interest_score(source_name, c.label, c.url, c.path, profile=profile),
            -c.depth,
            c.path_label.lower(),
        ),
        reverse=True,
    )


_CATEGORY_URL_RE = re.compile(
    r"(/c/|/category|/categorie|/categoria|/catalog|/catalogo|/k/|/s-|/l/|/markt|/marktplaats|"
    r"/recommerce/|/annunci-|/kaufen|/acheter|/search/|/collections?/|/products?/)",
    re.I,
)


_SITE_PRODUCT_URL_RE = re.compile(
    r"(/p/|/product/[^/?#]+|/products/[^/?#]+|/item/|/itm/|/ad/|/ads/|/annunci/[^/?#]+|/anzeige/[^/?#]+|/oferta/[^/?#]+|/listing/[^/?#]+|/product-detail)",
    re.I,
)


def normalize_category_url(url: str) -> str:
    parsed = urlparse(url)
    # Keep query only when it looks structurally meaningful for category/search,
    # otherwise remove tracking.
    query = parsed.query
    if query and not re.search(r"(category|cat|rubric|section|keyword|q|query|search|text|stext|type|page)", query, re.I):
        query = ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") or "/", "", query, ""))


def source_entrypoints(source_name: str) -> list[str]:
    if source_name in SOURCE_ENTRYPOINTS:
        return list(SOURCE_ENTRYPOINTS[source_name])

    source = get_source(source_name)
    roots: list[str] = []
    for template in source.search_url_templates:
        fake = template.format(query="spyengine", q="spyengine", raw_query="spyengine", limit=100)
        p = urlparse(fake)
        if p.scheme and p.netloc:
            roots.append(f"{p.scheme}://{p.netloc}/")
    # Dedup preserving order.
    out = []
    seen = set()
    for url in roots:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _clean_label(text: str, fallback_url: str = "") -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"^\W+|\W+$", "", text).strip()
    if 2 <= len(text) <= 80:
        return text

    parts = [p for p in urlparse(fallback_url).path.strip("/").split("/") if p]
    if parts:
        slug = parts[-1]
        slug = re.sub(r"[-_]+", " ", slug)
        slug = re.sub(r"\s+", " ", slug).strip()
        if slug:
            return slug[:80]

    host = urlparse(fallback_url).netloc
    return (host or fallback_url or "unknown")[:80]


def _same_site(url: str, base_url: str) -> bool:
    u = urlparse(url)
    b = urlparse(base_url)
    if not u.scheme or not u.netloc:
        return False
    return u.netloc.lower().replace("www.", "") == b.netloc.lower().replace("www.", "")



def _looks_like_category_url_not_noise(href: str, label: str) -> bool:
    parsed = urlparse(href)
    path = parsed.path.rstrip("/")
    parts = [p for p in path.strip("/").split("/") if p]
    label_s = (label or "").strip()

    if _SITE_PRODUCT_URL_RE.search(href):
        return False

    # Root/home URLs are not categories, even if they contain category_type.
    if not parts:
        return False

    # Language/root selectors like /en-nl or /it-it are not categories.
    if len(parts) == 1 and re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", parts[0], flags=re.I):
        return False

    # Fallback labels like "www.refurbed.it" came from empty root links.
    if re.fullmatch(r"(www\.)?[^/\s]+\.[a-z]{2,}", label_s, flags=re.I):
        return False

    # Generic /products is useful for broad discovery sometimes, but crawling it
    # as a category created duplicate pools.
    if re.search(r"/products?$", path, flags=re.I) and _GENERIC_CATEGORY_NAV_RE.match(label_s):
        return False

    return True


def _looks_like_category_link(href: str, label: str, parent_text: str = "") -> bool:
    # Skip checks must not include the entire parent/nav text:
    # a global nav often contains "login/privacy" near valid categories.
    joined = f"{href} {label} {parent_text}".lower()
    skip_probe = f"{href} {label}".lower()
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return False
    if not _looks_like_category_url_not_noise(href, label):
        return False
    if _SKIP_LINK_RE.search(skip_probe):
        return False
    if len(label) > 90:
        return False
    if _LANGUAGE_SWITCH_RE.match(label.strip()):
        return False
    if _GENERIC_CATEGORY_NAV_RE.match(label.strip()):
        return False
    if _GENERIC_DEAL_RE.match(label.strip()):
        return False
    if _CATEGORY_HARD_NOISE_RE.search(skip_probe):
        return False
    if re.search(r"\b\d{1,6}\s*(€|eur|chf|gbp|usd)\b", joined):
        return False
    if _CATEGORY_URL_RE.search(href):
        return True
    # Root navigation often has clean human labels without category-looking URLs.
    # Keep conservative but allow common nav/category labels.
    if re.search(
        r"\b(elettronica|casa|arredo|abbigliamento|scarpe|auto|moto|sport|giardino|bricolage|"
        r"informatica|telefonia|console|libri|musica|bambini|elettrodomestici|bagno|cucina|"
        r"electronics|home|fashion|motors|sports|garden|computers|phones|appliances|furniture|"
        r"kategorien|categorie|categorias|categories|rubriques)\b",
        joined,
        re.I,
    ):
        return True
    return False


def extract_site_category_links(
    html: str,
    *,
    source_name: str,
    base_url: str,
    parent_path: tuple[str, ...] = (),
    depth: int = 1,
    max_links: int = 250,
) -> list[SiteCategory]:
    """Extract candidate category/subcategory links from one site page.

    This is deliberately best-effort and source-agnostic. It reads the site's
    real navigation/links, not SpyEngine's internal taxonomy.
    """

    soup = BeautifulSoup(html or "", "html.parser")
    out: list[SiteCategory] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        if len(out) >= max_links:
            break
        href = str(a.get("href") or "").strip()
        url = normalize_category_url(urljoin(base_url, href))
        if not _same_site(url, base_url):
            continue

        text = a.get_text(" ", strip=True)
        parent_text = ""
        try:
            parent_text = a.parent.get_text(" ", strip=True)[:220] if a.parent else ""
        except Exception:
            parent_text = ""

        label = _clean_label(text, url)
        if not _looks_like_category_link(url, label, parent_text):
            continue

        if url in seen:
            continue
        seen.add(url)
        path = tuple([*parent_path, label])
        out.append(
            SiteCategory(
                source=source_name,
                label=label,
                url=url,
                path=path,
                depth=depth,
                parent_url=base_url,
            )
        )

    return sort_site_categories_for_target(source_name, out)




def _unlimited(value: int | None) -> bool:
    try:
        return int(value or 0) <= 0
    except Exception:
        return True


def _within_limit(count: int, limit: int | None) -> bool:
    return _unlimited(limit) or count < int(limit)



def iter_site_categories(
    *,
    source_name: str,
    client,
    max_depth: int = 0,
    max_categories: int = 0,
    max_links_per_page: int = 250,
    progress=None,
):
    """Yield site-native categories progressively.

    Unlike discover_site_categories(), this does not wait until the whole tree
    has been explored. The crawler can start processing the first category as
    soon as it is discovered.

    Semantics:
      - max_depth <= 0: unlimited depth, bounded by unique URLs
      - max_categories <= 0: unlimited categories, bounded by discovered URLs
    """

    roots = source_entrypoints(source_name)
    yielded = 0
    seen_urls: set[str] = set()
    yielded_urls: set[str] = set()
    queue: list[tuple[str, tuple[str, ...], int]] = [(root, tuple(), 0) for root in roots]

    while queue and _within_limit(yielded, max_categories):
        url, parent_path, depth = queue.pop(0)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        try:
            if progress:
                progress(f"[discover] {source_name} depth={depth} queue={len(queue)} yielded={yielded} -> {url}")
            response = client.get(url)
            response.raise_for_status()
            children = extract_site_category_links(
                response.text,
                source_name=source_name,
                base_url=url,
                parent_path=parent_path,
                depth=depth + 1,
                max_links=max_links_per_page,
            )
        except Exception as e:
            if progress:
                progress(f"[discover-error] {source_name} {url}: {e}")
            continue

        for child in children:
            if not _within_limit(yielded, max_categories):
                break
            if child.url in yielded_urls:
                continue
            yielded_urls.add(child.url)
            yielded += 1
            yield child

            if _unlimited(max_depth) or child.depth < int(max_depth):
                if child.url not in seen_urls:
                    queue.append((child.url, child.path, child.depth))


def discover_site_categories(
    *,
    source_name: str,
    client,
    max_depth: int = 0,
    max_categories: int = 0,
    max_links_per_page: int = 250,
    progress=None,
) -> list[SiteCategory]:
    """Return discovered categories as a list.

    For crawling, prefer iter_site_categories() so listing ingestion starts
    immediately instead of waiting for full tree discovery.
    """

    return list(
        iter_site_categories(
            source_name=source_name,
            client=client,
            max_depth=max_depth,
            max_categories=max_categories,
            max_links_per_page=max_links_per_page,
            progress=progress,
        )
    )




_PAGINATION_RE = re.compile(
    r"(?:[?&](?:page|p|pagina|pag)=\d+|/page/\d+|/pagina/\d+|/seite/\d+)",
    re.I,
)

_PAGE_PARAM_NAMES = {"page", "p", "pagina", "pag"}


def _strip_page_params(url: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    parsed = urlparse(url)
    query_pairs = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        if k.lower() in _PAGE_PARAM_NAMES:
            continue
        query_pairs.append((k, v))
    return parsed.path.rstrip("/"), tuple(sorted(query_pairs))


def _extract_page_number(url: str, label: str = "") -> int | None:
    parsed = urlparse(url)
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        if k.lower() in _PAGE_PARAM_NAMES:
            try:
                return int(v)
            except Exception:
                return None

    m = re.search(r"/(?:page|pagina|seite)/(\d+)", parsed.path, flags=re.I)
    if m:
        return int(m.group(1))

    if re.fullmatch(r"\d{1,4}", (label or "").strip()):
        return int(label.strip())

    return None


def _same_pagination_family(candidate_url: str, base_url: str) -> bool:
    """Reject facet/category/filter URLs that merely contain page=1.

    Pagination may only change the page parameter, not category/filter/path.
    """

    cand_path, cand_query = _strip_page_params(candidate_url)
    base_path, base_query = _strip_page_params(base_url)

    if cand_path != base_path:
        return False

    if cand_query != base_query:
        return False

    return True


def extract_pagination_links(html: str, *, base_url: str, max_pages: int = 0) -> list[str]:
    """Extract real pagination links from a category/listing page.

    Strict rules:
      - same site
      - same category path as base page
      - same non-page query params as base page
      - page number must advance beyond current page
      - max_pages <= 0 means all real pagination links found, not facet links
    """

    soup = BeautifulSoup(html or "", "html.parser")
    base_url = normalize_category_url(base_url)
    urls: list[str] = [base_url]
    seen: set[str] = {base_url}

    current_page = _extract_page_number(base_url) or 1

    for a in soup.find_all("a", href=True):
        if not should_continue_pages(len(urls), max_pages):
            break

        href = str(a.get("href") or "").strip()
        label = a.get_text(" ", strip=True).lower()
        url = normalize_category_url(urljoin(base_url, href))

        if url in seen or not _same_site(url, base_url):
            continue

        page_num = _extract_page_number(url, label)
        if page_num is None or page_num <= current_page:
            continue

        label_is_page = bool(
            re.fullmatch(
                r"(next|avanti|successiva|suivant|weiter|volgende|siguiente|>|»|\d{1,4})",
                label,
            )
        )
        if not _PAGINATION_RE.search(url) and not label_is_page:
            continue

        if not _same_pagination_family(url, base_url):
            continue

        seen.add(url)
        urls.append(url)

    return urls if _unlimited(max_pages) else urls[: max(1, int(max_pages))]


def should_continue_pages(count: int, max_pages: int | None) -> bool:
    return _within_limit(count, max_pages)



def category_page_urls(category: SiteCategory, *, max_pages: int = 0) -> list[str]:
    # Dry-run/discovery-safe page list. Real crawl expands pagination after
    # fetching the first category page with extract_pagination_links().
    return [category.url]


def should_continue_pages(count: int, max_pages: int | None) -> bool:
    return _within_limit(count, max_pages)
