from __future__ import annotations

import re
import time
import random
import requests

from .base import BasePlatform
from spyengine.core.models import Listing
from spyengine.utils.text import parse_price, parse_euro_price
from spyengine.utils.selectors import safe_text, safe_attr, debug_snapshot
from spyengine.services.browser import get_random_user_agent


class VintedPlatform(BasePlatform):
    name = "VINTED"

    TITLE_SELECTORS = [
        "[data-testid='item-title']",
        "[data-testid*='title']",
        "p[class*='title']",
        "a[title]",
        "a[aria-label]",
        "a",
    ]
    PRICE_SELECTORS = [
        "[data-testid='item-price']",
        "[data-testid*='price']",
        "span:has-text('€')",
        "div:has-text('€')",
    ]

    def _extract_vinted_api(self, item_id: str):
        try:
            r = requests.get(
                f"https://www.vinted.it/api/v2/items/{item_id}",
                headers={"User-Agent": get_random_user_agent(), "Accept": "application/json"},
                timeout=10,
            )
            if r.status_code == 200:
                item = r.json().get("item", {})
                price_raw = item.get("price") or {}
                price = None
                if isinstance(price_raw, dict):
                    price = price_raw.get("amount")
                elif isinstance(price_raw, (int, float, str)):
                    price = price_raw
                try:
                    price = float(price) if price is not None else None
                except Exception:
                    price = None

                photos = item.get("photos") or []
                img = None
                if photos:
                    img = photos[0].get("url") or photos[0].get("full_size_url")

                return {
                    "title": item.get("title") or "",
                    "description": item.get("description", "") or "",
                    "image_url": img,
                    "price": price,
                }
        except Exception as e:
            if self.logger:
                self.logger.think(f"Vinted API item {item_id} non disponibile: {e}")
        return {}

    def _extract_card(self, card, url: str) -> tuple[str, float]:
        # Keep every read scoped to the card: no broad card.text_content() unless all precise selectors fail.
        title = safe_attr(card, ["a[title]"], "title") or safe_attr(card, ["a[aria-label]"], "aria-label")
        if not title:
            title = safe_text(card, self.TITLE_SELECTORS, min_len=2)

        price_text = safe_text(card, self.PRICE_SELECTORS, min_len=1)
        price = parse_euro_price(price_text)

        # Fallback only after scoped selectors failed. parse_euro_price avoids leading badge numbers.
        if price >= 999:
            try:
                fallback_text = card.inner_text(timeout=1200) or ""
                price = parse_euro_price(fallback_text, parse_price(price_text))
                if not title:
                    lines = [x.strip() for x in fallback_text.splitlines() if x.strip()]
                    title = next((x for x in lines if "€" not in x and len(x) > 2), "Vinted item")
            except Exception:
                pass

        # Avoid polluted titles such as full concatenated cards.
        if "€" in title or len(title) > 120:
            title = title.split("€")[0].strip()[:100] or "Vinted item"

        return title or "Vinted item", price

    def _extract_detail_ui(self, context, listing: Listing):
        page = context.new_page()
        result = {}
        try:
            self.browser.human_delay(1.0, 2.5)
            self.browser.block_heavy_resources(page, allow_images=True)
            self.browser.safe_goto(page, listing.url, timeout=22000, wait_until="domcontentloaded", logger=self.logger)
            self.browser.dismiss_cookie_banner(page, self.logger)

            desc = safe_text(page, ["[data-testid='description']", "[itemprop='description']", ".details-description", "[data-testid='item-description']", ".item-description"], timeout=5000, min_len=8)
            if desc:
                result["description"] = desc
            img = safe_attr(page, ["[data-testid='item-photos'] img", "img[src*='item_image']", "img"], "src", timeout=3000)
            if img:
                result["image_url"] = img
        except Exception as e:
            if self.logger:
                self.logger.think(f"Errore dettaglio Vinted UI {listing.id}: {e}")
        finally:
            page.close()
        return result

    def search(self):
        if not self.browser.start():
            return
        context = self.browser.new_context()
        if not context:
            return
        try:
            for keyword in self.config.search_keywords:
                page = context.new_page()
                try:
                    q = keyword.replace(" ", "%20")
                    url = f"https://www.vinted.it/catalog?search_text={q}&order=newest_first"
                    self.browser.block_heavy_resources(page, allow_images=False)
                    ok = self.browser.safe_goto(page, url, timeout=25000, wait_until="domcontentloaded", logger=self.logger)
                    self.browser.dismiss_cookie_banner(page, self.logger)
                    time.sleep(random.uniform(1.5, 3.0))

                    try:
                        page.wait_for_selector("[data-testid='grid-item']", timeout=15000)
                    except Exception:
                        if self.config.debug_snapshots:
                            debug_snapshot(page, f"vinted_no_grid_{keyword}", self.config.debug_dir, self.logger)
                        if not ok:
                            continue

                    cards = page.locator("[data-testid='grid-item']")
                    count = cards.count()
                    if self.logger:
                        self.logger.think(f"Vinted '{keyword}': {count} card")

                    for i in range(min(count, self.config.max_items_per_keyword)):
                        card = cards.nth(i)
                        try:
                            href = safe_attr(card, ["a[href*='/items/']", "a"], "href")
                            if not href:
                                continue
                            item_url = href if href.startswith("http") else f"https://www.vinted.it{href}"
                            m = re.search(r"/items/(\d+)", item_url)
                            listing_id = f"vinted_{m.group(1)}" if m else f"vinted_{abs(hash(item_url))}"
                            if self._already_seen(listing_id):
                                continue

                            title, price = self._extract_card(card, item_url)
                            listing = Listing(listing_id, self.name, title, price, item_url, description=title)

                            # API-first once we have the item id: faster and cleaner than DOM detail.
                            detail = self._extract_vinted_api(m.group(1)) if m else {}
                            if self.config.fetch_details and not detail.get("description"):
                                detail.update({k: v for k, v in self._extract_detail_ui(context, listing).items() if v})

                            listing.title = detail.get("title") or listing.title
                            listing.description = detail.get("description") or listing.description or listing.title
                            listing.image_url = detail.get("image_url") or listing.image_url
                            if detail.get("price") is not None:
                                listing.price = float(detail["price"])

                            yield listing
                        except Exception as e:
                            if self.logger:
                                self.logger.think(f"Errore parsing Vinted card scoped: {e}")
                            continue
                except Exception as e:
                    if self.config.debug_snapshots:
                        debug_snapshot(page, f"vinted_error_{keyword}", self.config.debug_dir, self.logger)
                    if self.logger:
                        self.logger.warning(f"Errore Vinted ricerca '{keyword}': {e}")
                finally:
                    page.close()
                time.sleep(random.uniform(2.0, 5.0))
        finally:
            context.close()
