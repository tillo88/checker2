from __future__ import annotations

import re
import time
import random

from .base import BasePlatform
from spyengine.core.models import Listing
from spyengine.utils.selectors import (
    parse_euro_price,
    debug_snapshot,
    normalize_url,
    first_text,
)


class WallapopPlatform(BasePlatform):
    name = "WALLAPOP"

    SEARCH_URL = "https://it.wallapop.com/app/search?keywords={q}&filters_source=search_box&order_by=newest"

    def _item_id_from_url(self, url: str) -> str:
        clean = (url or "").split("?")[0].rstrip("/")
        for pat in [r"-(\d+)$", r"/(\d{6,})$"]:
            m = re.search(pat, clean)
            if m:
                return f"wallapop_{m.group(1)}"
        return f"wallapop_{abs(hash(clean or url))}"

    def _is_item_url(self, url: str) -> bool:
        if not url:
            return False
        bad = ["/app/search", "/login", "/register", "/help", "/terms", "/privacy", "adjust.com"]
        if any(x in url for x in bad):
            return False
        clean = url.split("?")[0]
        return "wallapop.com" in url and ("/item/" in clean or bool(re.search(r"-\d{6,}$", clean)))

    def _clean_title(self, raw_text: str, url: str = "") -> str:
        lines = [l.strip() for l in (raw_text or "").splitlines() if l.strip()]
        cleaned = []

        for line in lines:
            low = line.lower()

            # Rimuove contatore immagini tipo "1 / 6"
            if re.fullmatch(r"\d+\s*/\s*\d+", line):
                continue

            # Rimuove righe solo prezzo
            if re.fullmatch(r"\d{1,5}(?:[.,]\d{1,2})?\s*(?:€|eur)?", low, re.IGNORECASE):
                continue

            # Rimuove righe di UI/comandi
            if low in {
                "home", "preferiti", "inserisci", "inbox", "tu", "registrati o accedi",
                "accetta tutto", "rifiuta tutto", "privacy? scegli tu.", "personalizza la tua scelta",
            }:
                continue

            if "€" in line and len(line) < 30:
                continue

            cleaned.append(line)

        if cleaned:
            # Di solito il titolo sta subito dopo prezzo/contatore; scegli la prima riga descrittiva non UI.
            return cleaned[0][:180]

        # Fallback da slug URL
        clean_url = (url or "").split("?")[0].rstrip("/")
        slug = clean_url.split("/item/")[-1] if "/item/" in clean_url else clean_url.split("/")[-1]
        slug = re.sub(r"-\d+$", "", slug)
        slug = slug.replace("-", " ").strip()
        return slug.capitalize()[:180] if slug else "Wallapop item"

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

            self.browser.dismiss_cookie_banner(page, self.logger)

            desc = first_text(page, [
                "[class*='description']",
                "[data-testid*='description']",
                "section p",
                "p",
            ], timeout=3000)
            if desc:
                detail["description"] = desc

            try:
                img = page.locator("img[src*='cdn.wallapop'], img[src*='wallapop'], img").first
                if img.count() > 0:
                    detail["image_url"] = img.get_attribute("src")
            except Exception:
                pass
        except Exception as e:
            if self.logger:
                self.logger.think(f"Errore dettaglio Wallapop {listing.id}: {e}")
        finally:
            page.close()
        return detail

    def _anchor_to_listing(self, anchor):
        href = ""
        try:
            href = anchor.get_attribute("href") or ""
        except Exception:
            return None

        url = normalize_url(href, "https://it.wallapop.com")
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

    def search(self):
        if not self.browser.start():
            return
        context = self.browser.new_context()
        if not context:
            return

        try:
            yielded = 0
            max_total = getattr(self.config, "max_total_items", None)
            max_per_kw = getattr(self.config, "max_items_per_keyword", 10)
            debug = getattr(self.config, "debug_snapshots", False)
            skip_details = getattr(self.config, "skip_details", False)

            for keyword in self.config.search_keywords:
                page = context.new_page()
                try:
                    q = keyword.replace(" ", "%20")
                    self.browser.block_heavy_resources(page, allow_images=False)

                    try:
                        page.goto(self.SEARCH_URL.format(q=q), timeout=18000, wait_until="domcontentloaded")
                    except Exception as e:
                        if self.logger:
                            self.logger.warning(f"goto non completato (domcontentloaded): {e}")
                        try:
                            page.goto(self.SEARCH_URL.format(q=q), timeout=8000, wait_until="commit")
                        except Exception:
                            pass

                    self.browser.human_delay(1.5, 2.5)
                    self.browser.dismiss_cookie_banner(page, self.logger)
                    self.browser.human_delay(1.0, 2.0)

                    # Prova ad attendere link prodotto veri. Se non arrivano, snapshot/debug aiuta.
                    try:
                        page.wait_for_selector("a[href*='/item/'], a[href*='wallapop.com/item/']", timeout=7000)
                    except Exception:
                        pass

                    if debug:
                        debug_snapshot(page, f"wallapop_{keyword}", logger=self.logger)

                    anchors = page.locator("a[href*='/item/'], a[href*='wallapop.com/item/']")
                    try:
                        count = anchors.count()
                    except Exception:
                        count = 0

                    if self.logger:
                        self.logger.think(f"Wallapop '{keyword}': {count} item anchor")

                    produced_for_kw = 0
                    seen_urls = set()

                    for i in range(min(count, 120)):
                        if produced_for_kw >= max_per_kw:
                            break
                        if max_total is not None and yielded >= max_total:
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
                        yielded += 1
                        yield listing

                    if self.logger:
                        self.logger.think(f"Wallapop '{keyword}': prodotti {produced_for_kw} listing validi")
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Errore Wallapop ricerca '{keyword}': {e}")
                finally:
                    page.close()

                time.sleep(random.uniform(2.0, 4.0))
        finally:
            context.close()
