from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .extractors import extract_specs_from_text, parse_price
from .models import HarvestListing


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _jsonld_objects(html: str) -> Iterable[dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = _as_list(data)
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            if "@graph" in item:
                stack.extend(_as_list(item.get("@graph")))
            yield item



_PRODUCT_URL_RE = re.compile(
    r"(/p/|/product/|/products/[^/?#]+|/item/|/itm/|/ad/|/ads/|/annunci/|/anzeige/|/oferta|/oferty/|/listing|/listings|/product-detail)",
    re.I,
)

_CATEGORY_OR_NAV_URL_RE = re.compile(
    r"(/c/|/category|/categories|/categorie|/categoria|/catalog|/catalogo|/search|/recherche|/zoeken|/q/|/s-|/l/|/collections?$|/products/?$|/deals/?$)",
    re.I,
)

_NAV_TITLE_RE = re.compile(
    r"^(view all|all categories|show all|login|privacy|cookie|terms|help|aiuto|accessories|other|home|menu|categorie|categories)$",
    re.I,
)

_NOISE_TEXT_RE = re.compile(
    r"(mon\s*-\s*fri|0800\s*222|view all|all categories|privacy|cookie|terms|newsletter|"
    r"smartphones\s+laptops\s+tablets|apple weeks\s+smartphones|vacuum cleaners\s+.*smartphones)",
    re.I,
)


def _slug_title_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/").split("/")
    slug = path[-1] if path else ""
    slug = re.sub(r"[-_]+", " ", slug).strip()
    return re.sub(r"\s+", " ", slug)


def clean_listing_title(anchor_text: str, url: str, parent_text: str = "") -> str:
    text = re.sub(r"\s+", " ", str(anchor_text or "")).strip()
    slug = _slug_title_from_url(url)

    too_noisy = bool(_NOISE_TEXT_RE.search(text)) or len(text) > 120
    if too_noisy and _PRODUCT_URL_RE.search(url) and slug:
        return slug[:120]

    if 6 <= len(text) <= 120 and not _NOISE_TEXT_RE.search(text):
        return text

    if _PRODUCT_URL_RE.search(url) and slug:
        return slug[:120]

    parent = re.sub(r"\s+", " ", str(parent_text or "")).strip()
    if 6 <= len(parent) <= 120 and not _NOISE_TEXT_RE.search(parent):
        return parent

    return (text or slug)[:120]


def listing_quality(url: str, title: str, parent_text: str, price: float | None) -> dict:
    """Prefilter generic anchors before they reach catalog/classifier."""
    url = str(url or "")
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    title_l = title.lower()

    if not title or len(title) < 6:
        return {"accept": False, "reason": "title_too_short"}

    if _NAV_TITLE_RE.match(title_l):
        return {"accept": False, "reason": "nav_title"}

    product_url = bool(_PRODUCT_URL_RE.search(url))
    category_url = bool(_CATEGORY_OR_NAV_URL_RE.search(url))

    if _NOISE_TEXT_RE.search(title) and not product_url:
        return {"accept": False, "reason": "noise_title"}

    if price is not None and not _NAV_TITLE_RE.match(title_l):
        return {"accept": True, "reason": "price_card", "product_url": product_url, "category_url": category_url}

    if product_url and not category_url:
        return {"accept": True, "reason": "product_url", "product_url": product_url, "category_url": category_url}

    if category_url:
        return {"accept": False, "reason": "category_or_nav_url"}

    return {"accept": False, "reason": "weak_generic_anchor"}


def parse_jsonld_products(html: str, *, source: str, query: str, base_url: str) -> list[HarvestListing]:
    out: list[HarvestListing] = []

    for obj in _jsonld_objects(html):
        typ = obj.get("@type") or obj.get("type")
        types = [str(x).lower() for x in _as_list(typ)]
        if not any(t in {"product", "offer", "listitem"} for t in types):
            continue

        product = obj.get("item") if isinstance(obj.get("item"), dict) else obj
        title = product.get("name") or product.get("title") or obj.get("name") or ""
        if not title:
            continue

        offers = product.get("offers") or obj.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        price = None
        currency = ""
        if isinstance(offers, dict):
            raw_price = offers.get("price") or offers.get("lowPrice")
            try:
                price = float(str(raw_price).replace(",", ".")) if raw_price is not None else None
            except ValueError:
                price = None
            currency = str(offers.get("priceCurrency") or "")

        url = product.get("url") or obj.get("url") or ""
        image = product.get("image") or obj.get("image") or ""
        if isinstance(image, list):
            image = image[0] if image else ""

        title_text = str(title).strip()
        out.append(
            HarvestListing(
                source=source,
                title=title_text,
                url=urljoin(base_url, str(url)) if url else base_url,
                price=price,
                currency=currency,
                image_url=urljoin(base_url, str(image)) if image else "",
                query=query,
                specs=extract_specs_from_text(title_text),
                raw={"jsonld": obj},
            )
        )

    return out


def _cardish_parent_text(anchor) -> str:
    """Return likely product-card text, avoiding full nav/footer blocks."""
    parent = anchor.parent
    best = anchor.get_text(" ", strip=True)
    for _ in range(4):
        if parent is None:
            break
        text = parent.get_text(" ", strip=True)
        if 20 <= len(text) <= 900:
            return text
        if len(best) < len(text) <= 900:
            best = text
        parent = parent.parent
    return best


def parse_generic_listing_cards(
    html: str,
    *,
    source: str,
    query: str,
    base_url: str,
    max_items: int = 100,
) -> list[HarvestListing]:
    """Best-effort HTML parser with strict prefiltering.

    The generic crawler is conservative: category/nav/footer links must not
    become products. If a site needs more recall, add a source-specific adapter.
    """

    soup = BeautifulSoup(html or "", "html.parser")
    out: list[HarvestListing] = []
    seen: set[str] = set()

    for listing in parse_jsonld_products(html, source=source, query=query, base_url=base_url):
        key = listing.fingerprint()
        if key not in seen:
            seen.add(key)
            out.append(listing)

    for a in soup.find_all("a", href=True):
        if len(out) >= max_items:
            break

        href = str(a.get("href") or "")
        if href.startswith("#") or href.lower().startswith("javascript:"):
            continue

        parent_text = _cardish_parent_text(a)
        url = urljoin(base_url, href)
        title = clean_listing_title(a.get_text(" ", strip=True), url, parent_text)

        price, currency = parse_price(parent_text)
        quality = listing_quality(url, title, parent_text, price)
        if not quality.get("accept"):
            continue

        spec_text = parent_text if len(parent_text) <= 900 and not _NOISE_TEXT_RE.search(parent_text) else title

        listing = HarvestListing(
            source=source,
            title=title,
            url=url,
            price=price,
            currency=currency,
            query=query,
            specs=extract_specs_from_text(spec_text),
            raw={"text": spec_text[:1000], "quality": quality},
        )
        key = listing.fingerprint()
        if key in seen:
            continue
        seen.add(key)
        out.append(listing)

    return out[:max_items]
