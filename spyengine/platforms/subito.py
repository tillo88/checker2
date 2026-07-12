from __future__ import annotations

import json
import re
import time
import random
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .base import BasePlatform
from spyengine.core.models import Listing
from spyengine.utils.selectors import (
    parse_euro_price,
    debug_snapshot,
    normalize_url,
    first_text,
)


class SubitoPlatform(BasePlatform):
    name = "SUBITO"

    SEARCH_URL = "https://www.subito.it/annunci-italia/vendita/usato/?q={q}&o=date"

    REQUEST_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Pragma": "no-cache",
        "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Brave";v="128"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    }

    def _is_access_denied_text(self, text: str) -> bool:
        blob = (text or "").lower()
        return any(m in blob for m in [
            "access denied",
            "you don't have permission to access",
            "errors.edgesuite.net",
            "reference #",
        ])

    def _is_access_denied(self, page) -> bool:
        try:
            title = page.title(timeout=1500) or ""
        except Exception:
            title = ""
        try:
            body = page.locator("body").first.text_content(timeout=1500) or ""
        except Exception:
            body = ""
        return self._is_access_denied_text(f"{title}\n{body}")

    def _item_id_from_url(self, url: str) -> str:
        clean = (url or "").split("?")[0].rstrip("/")
        patterns = [
            r"-(\d+)\.htm$",
            r"-([a-f0-9]{8,})\.htm$",
            r"/([^/]+)\.htm$",
        ]
        for pat in patterns:
            m = re.search(pat, clean, re.IGNORECASE)
            if m:
                return f"subito_{m.group(1)}"
        return f"subito_{abs(hash(clean or url))}"

    def _is_item_url(self, url: str) -> bool:
        if not url:
            return False
        bad = [
            "/annunci-", "/aiuto", "/info", "/privacy", "/terms", "/login",
            "/registrati", "/account", "/messaggi", "/preferiti",
        ]
        clean = url.split("?")[0]
        if any(x in clean for x in bad):
            return False
        return "subito.it" in url and clean.endswith(".htm")

    def _feature_price(self, product: dict) -> float:
        features = product.get("features", {}) or {}
        price_feature = features.get("/price") or {}
        values = price_feature.get("values") or []
        if values:
            raw = values[0].get("key") or values[0].get("value")
            try:
                return float(str(raw).replace(",", "."))
            except Exception:
                pass

        # fallback su possibili campi moderni
        for key in ["price", "priceValue", "cost"]:
            raw = product.get(key)
            if raw is None:
                continue
            if isinstance(raw, dict):
                raw = raw.get("value") or raw.get("amount") or raw.get("key")
            try:
                return float(str(raw).replace(",", "."))
            except Exception:
                pass

        return 999.0

    def _feature_shipping(self, product: dict) -> str:
        try:
            values = product.get("features", {}).get("/item_shippable", {}).get("values", [])
            if values and values[0].get("value"):
                return "Spedizione disponibile"
        except Exception:
            pass
        return ""

    def _location(self, product: dict) -> str:
        geo = product.get("geo", {}) or {}
        town = ((geo.get("town") or {}).get("value")) or ""
        city = ((geo.get("city") or {}).get("shortName")) or ""
        if town and city:
            return f"{town} ({city})"
        return town or city or ""

    def _image_url(self, product: dict) -> str | None:
        # Subito cambia spesso forma immagini. Provo campi frequenti senza rompere.
        image = product.get("image")
        if isinstance(image, str) and image.startswith("http"):
            return image
        if isinstance(image, dict):
            for key in ["url", "src", "large", "medium", "small"]:
                val = image.get(key)
                if isinstance(val, str) and val.startswith("http"):
                    return val

        images = product.get("images") or product.get("photos") or []
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, str) and first.startswith("http"):
                return first
            if isinstance(first, dict):
                for key in ["url", "src", "large", "medium", "small"]:
                    val = first.get(key)
                    if isinstance(val, str) and val.startswith("http"):
                        return val
        return None

    def _listing_from_product(self, product: dict) -> Listing | None:
        urn = product.get("urn")
        title = product.get("subject") or product.get("title") or ""
        url = ((product.get("urls") or {}).get("default")) or product.get("url") or product.get("link") or ""
        if not url:
            return None

        url = normalize_url(url, "https://www.subito.it").split("?")[0]
        listing_id = f"subito_{urn}" if urn else self._item_id_from_url(url)
        price = self._feature_price(product)
        location = self._location(product)
        shipping = self._feature_shipping(product)
        extra = " | ".join(x for x in [location, shipping] if x)

        if product.get("sold", False):
            return None

        return Listing(
            id=listing_id,
            platform=self.name,
            title=title or "Subito item",
            price=price,
            url=url,
            description=title or "",
            image_url=self._image_url(product),
            extra_info=extra,
            raw=product,
        )

    def _extract_next_data_items(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            return []

        data = json.loads(script.string)

        # Forma usata dal repo morrolinux/subito-it-searcher:
        # props.pageProps.initialState.items.list[].item
        try:
            wrappers = data["props"]["pageProps"]["initialState"]["items"]["list"]
            products = []
            for wrapper in wrappers:
                product = wrapper.get("item") if isinstance(wrapper, dict) else None
                if product:
                    products.append(product)
            if products:
                return products
        except Exception:
            pass

        # Fallback generico: scan ricorsivo di dict con subject+urls/features
        found = []

        def walk(obj):
            if isinstance(obj, dict):
                if (
                    ("subject" in obj or "title" in obj)
                    and ("urls" in obj or "url" in obj or "link" in obj)
                    and ("features" in obj or "price" in obj or "priceValue" in obj)
                ):
                    found.append(obj)
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)

        walk(data)
        return found

    def _request_search(self, keyword: str) -> tuple[list[Listing], str]:
        q = keyword.replace(" ", "%20")
        url = self.SEARCH_URL.format(q=q)

        session = requests.Session()
        session.headers.update(self.REQUEST_HEADERS)

        try:
            r = session.get(url, timeout=(6, 12), allow_redirects=True)
        except requests.exceptions.Timeout:
            return [], "requests timeout"
        except requests.RequestException as e:
            return [], f"requests error: {e}"

        if self._is_access_denied_text(r.text):
            return [], "access_denied"

        if r.status_code != 200:
            return [], f"http_{r.status_code}"

        try:
            products = self._extract_next_data_items(r.text)
        except Exception as e:
            return [], f"next_data_parse_error: {e}"

        listings = []
        seen = set()
        for product in products:
            listing = self._listing_from_product(product)
            if not listing or listing.id in seen:
                continue
            seen.add(listing.id)
            listings.append(listing)

        return listings, f"ok_{len(listings)}"

    def _clean_title(self, text: str, url: str = "") -> str:
        lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
        cleaned = []

        for line in lines:
            low = line.lower()
            if "€" in line:
                continue
            if re.fullmatch(r"\d{1,5}(?:[.,]\d{1,2})?", line):
                continue
            if low in {"preferito", "sponsorizzato", "vendo", "vedi annuncio", "subito"}:
                continue
            if len(line) < 3:
                continue
            cleaned.append(line)

        if cleaned:
            return cleaned[0][:180]

        clean_url = (url or "").split("?")[0].rstrip("/")
        slug = clean_url.split("/")[-1]
        slug = re.sub(r"-\d+\.htm$", "", slug)
        slug = slug.replace("-", " ").replace(".htm", "").strip()
        return slug.capitalize()[:180] if slug else "Subito item"

    def _details(self, context, listing: Listing):
        page = context.new_page()
        detail = {}
        try:
            self.browser.human_delay(1.0, 2.5)
            self.browser.block_heavy_resources(page, allow_images=True)
            try:
                page.goto(listing.url, timeout=18000, wait_until="domcontentloaded")
            except Exception:
                try:
                    page.goto(listing.url, timeout=8000, wait_until="commit")
                except Exception:
                    pass

            if self._is_access_denied(page):
                if self.logger:
                    self.logger.warning("Subito dettaglio bloccato da Access Denied / EdgeSuite")
                return detail

            self.browser.dismiss_cookie_banner(page, self.logger)

            desc = first_text(page, [
                "[data-cy='ad-description']",
                "[data-testid*='description']",
                "[class*='description']",
                "section p",
                "p",
            ], timeout=3000, min_len=10)
            if desc:
                detail["description"] = desc

            try:
                img = page.locator("img[src*='subito'], img").first
                if img.count() > 0:
                    detail["image_url"] = img.get_attribute("src")
            except Exception:
                pass
        except Exception as e:
            if self.logger:
                self.logger.think(f"Errore dettaglio Subito {listing.id}: {e}")
        finally:
            page.close()
        return detail

    def _anchor_to_listing(self, anchor):
        try:
            href = anchor.get_attribute("href") or ""
        except Exception:
            return None

        url = normalize_url(href, "https://www.subito.it")
        if not self._is_item_url(url):
            return None

        text = ""
        try:
            text = anchor.inner_text(timeout=1200) or ""
        except Exception:
            try:
                text = anchor.text_content(timeout=1200) or ""
            except Exception:
                text = ""

        title = self._clean_title(text, url)
        price = parse_euro_price(text, 999.0)

        return Listing(
            id=self._item_id_from_url(url),
            platform=self.name,
            title=title,
            price=price,
            url=url.split("?")[0],
            description=title,
            raw={"anchor_text": text[:1000]},
        )

    def _playwright_fallback(self, context, keyword: str, yielded_so_far: int):
        max_total = getattr(self.config, "max_total_items", None)
        max_per_kw = getattr(self.config, "max_items_per_keyword", 10)
        debug = getattr(self.config, "debug_snapshots", False)
        skip_details = getattr(self.config, "skip_details", False)

        page = context.new_page()
        try:
            q = keyword.replace(" ", "%20")
            self.browser.block_heavy_resources(page, allow_images=False)

            try:
                page.goto(self.SEARCH_URL.format(q=q), timeout=18000, wait_until="domcontentloaded")
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"goto non completato Subito: {e}")
                try:
                    page.goto(self.SEARCH_URL.format(q=q), timeout=8000, wait_until="commit")
                except Exception:
                    pass

            self.browser.human_delay(1.5, 2.5)

            if debug:
                debug_snapshot(page, f"subito_{keyword}", logger=self.logger)

            if self._is_access_denied(page):
                if self.logger:
                    self.logger.warning("Subito Playwright bloccato da Access Denied / EdgeSuite")
                return

            self.browser.dismiss_cookie_banner(page, self.logger)
            self.browser.human_delay(2.0, 3.0)

            anchors = page.locator("a[href$='.htm'], a[href*='.htm?']")
            try:
                count = anchors.count()
            except Exception:
                count = 0

            if self.logger:
                self.logger.think(f"Subito '{keyword}': {count} item anchor via Playwright fallback")

            produced_for_kw = 0
            seen_urls = set()

            for i in range(min(count, 120)):
                if produced_for_kw >= max_per_kw:
                    break
                if max_total is not None and yielded_so_far >= max_total:
                    if self.logger:
                        self.logger.warning("Raggiunto max_total_items, interrompo la piattaforma corrente")
                    return

                listing = self._anchor_to_listing(anchors.nth(i))
                if not listing or listing.url in seen_urls:
                    continue
                seen_urls.add(listing.url)

                if self._already_seen(listing.id):
                    continue

                if not skip_details:
                    detail = self._details(context, listing)
                    listing.description = detail.get("description") or listing.description or listing.title
                    listing.image_url = detail.get("image_url") or listing.image_url

                produced_for_kw += 1
                yielded_so_far += 1
                yield listing

        finally:
            page.close()

    def search(self):
        yielded = 0
        max_total = getattr(self.config, "max_total_items", None)
        max_per_kw = getattr(self.config, "max_items_per_keyword", 10)
        skip_details = getattr(self.config, "skip_details", False)

        # 1) Requests + __NEXT_DATA__, ispirato al repo morrolinux/subito-it-searcher.
        for keyword in self.config.search_keywords:
            if max_total is not None and yielded >= max_total:
                if self.logger:
                    self.logger.warning("Raggiunto max_total_items, interrompo la piattaforma corrente")
                return

            listings, status = self._request_search(keyword)
            if self.logger:
                self.logger.think(f"Subito requests '{keyword}': {status}")

            produced = 0
            for listing in listings:
                if produced >= max_per_kw:
                    break
                if max_total is not None and yielded >= max_total:
                    if self.logger:
                        self.logger.warning("Raggiunto max_total_items, interrompo la piattaforma corrente")
                    return
                if self._already_seen(listing.id):
                    continue
                produced += 1
                yielded += 1
                yield listing

            if produced > 0:
                if self.logger:
                    self.logger.think(f"Subito '{keyword}': prodotti {produced} listing via requests/__NEXT_DATA__")
                time.sleep(random.uniform(1.0, 2.0))
                continue

            # Se requests è Access Denied, Playwright di solito è inutile ma lo lasciamo per snapshot/debug.
            if self.logger and status == "access_denied":
                self.logger.warning("Subito requests bloccato da Access Denied / EdgeSuite; provo fallback diagnostico Playwright")

            if not self.browser.start():
                continue
            context = self.browser.new_context()
            if not context:
                continue
            try:
                for listing in self._playwright_fallback(context, keyword, yielded):
                    if skip_details:
                        pass
                    yielded += 1
                    yield listing
            finally:
                context.close()

            time.sleep(random.uniform(2.0, 4.0))
