from __future__ import annotations

import base64
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from .base import BasePlatform
from spyengine.core.models import Listing


class EbayPlatform(BasePlatform):
    name = "EBAY"

    def __init__(self, config, logger=None, browser=None, memory=None):
        super().__init__(config, logger=logger, browser=browser, memory=memory)
        self._token: Optional[str] = None
        self._token_expires_at: datetime = datetime.min.replace(tzinfo=timezone.utc)

    def _env(self) -> str:
        raw = os.environ.get("EBAY_ENV", "production").strip().lower()
        return "sandbox" if raw in {"sandbox", "sand", "test"} else "production"

    def _api_root(self) -> str:
        return "https://api.sandbox.ebay.com" if self._env() == "sandbox" else "https://api.ebay.com"

    def _browse_search_endpoint(self) -> str:
        return f"{self._api_root()}/buy/browse/v1/item_summary/search"

    def _oauth_endpoint(self) -> str:
        return f"{self._api_root()}/identity/v1/oauth2/token"

    def _client_id(self) -> str:
        # Retrocompatibile: EBAY_APP_ID nel vecchio Finding API è anche il Client ID/App ID.
        env_name = getattr(self.config, "ebay_app_id_env", "EBAY_APP_ID")
        return (
            os.environ.get("EBAY_CLIENT_ID")
            or os.environ.get(env_name)
            or os.environ.get("EBAY_APP_ID")
            or ""
        ).strip()

    def _client_secret(self) -> str:
        # eBay Developer Console lo chiama Cert ID. Accettiamo entrambi i nomi.
        return (
            os.environ.get("EBAY_CLIENT_SECRET")
            or os.environ.get("EBAY_CERT_ID")
            or ""
        ).strip()

    def _marketplace_id(self) -> str:
        return os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_IT").strip() or "EBAY_IT"

    def _get_access_token(self) -> Optional[str]:
        now = datetime.now(timezone.utc)
        if self._token and now < self._token_expires_at:
            return self._token

        client_id = self._client_id()
        client_secret = self._client_secret()

        if not client_id:
            if self.logger:
                self.logger.warning("[eBay] EBAY_APP_ID/EBAY_CLIENT_ID mancante")
            return None

        if not client_secret:
            if self.logger:
                self.logger.warning(
                    "[eBay] EBAY_CLIENT_SECRET o EBAY_CERT_ID mancante. "
                    "La Browse API richiede OAuth client credentials."
                )
            return None

        basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")

        try:
            r = requests.post(
                self._oauth_endpoint(),
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "client_credentials",
                    "scope": "https://api.ebay.com/oauth/api_scope",
                },
                timeout=(6, 15),
            )
        except requests.exceptions.Timeout:
            if self.logger:
                self.logger.warning("[eBay] OAuth timeout")
            return None
        except requests.RequestException as e:
            if self.logger:
                self.logger.warning(f"[eBay] OAuth errore rete: {e}")
            return None

        if r.status_code != 200:
            if self.logger:
                self.logger.warning(f"[eBay] OAuth HTTP {r.status_code}: {r.text[:220]}")
            return None

        try:
            data = r.json()
        except Exception:
            if self.logger:
                self.logger.warning(f"[eBay] OAuth risposta non JSON: {r.text[:220]}")
            return None

        token = data.get("access_token")
        expires_in = int(data.get("expires_in", 7200) or 7200)

        if not token:
            if self.logger:
                self.logger.warning("[eBay] OAuth: access_token assente")
            return None

        self._token = token
        self._token_expires_at = now + timedelta(seconds=max(60, expires_in - 120))

        if self.logger:
            self.logger.think(f"[eBay] OAuth token OK ({self._env()})")

        return self._token

    def _headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": self._marketplace_id(),
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def _price(self, item: dict) -> float:
        for key in ["price", "currentBidPrice"]:
            p = item.get(key)
            if isinstance(p, dict):
                try:
                    return float(p.get("value", "999"))
                except Exception:
                    pass
        return 999.0

    def _image(self, item: dict) -> Optional[str]:
        img = item.get("image")
        if isinstance(img, dict):
            return img.get("imageUrl")
        return None

    def _location(self, item: dict) -> str:
        loc = item.get("itemLocation") or {}
        parts = []
        for key in ["city", "stateOrProvince", "country"]:
            val = loc.get(key)
            if val:
                parts.append(str(val))
        return ", ".join(parts)

    def _extra(self, item: dict) -> str:
        chunks = []
        condition = item.get("condition")
        if condition:
            chunks.append(str(condition))

        loc = self._location(item)
        if loc:
            chunks.append(loc)

        buying = item.get("buyingOptions") or []
        if buying:
            chunks.append("/".join(str(x) for x in buying))

        shipping = item.get("shippingOptions") or []
        if shipping:
            first = shipping[0] or {}
            cost = first.get("shippingCost")
            if isinstance(cost, dict):
                val = cost.get("value")
                cur = cost.get("currency")
                if val:
                    chunks.append(f"spedizione {val} {cur or ''}".strip())

        return " | ".join(chunks)

    def _listing_from_item(self, item: dict) -> Optional[Listing]:
        item_id = item.get("itemId")
        title = item.get("title") or ""
        url = item.get("itemWebUrl") or item.get("itemAffiliateWebUrl") or ""

        if not item_id or not url or not title:
            return None

        return Listing(
            id=f"ebay_{item_id}",
            platform=self.name,
            title=title,
            price=self._price(item),
            url=url,
            description=title,
            image_url=self._image(item),
            extra_info=self._extra(item),
            raw=item,
        )

    def _search_keyword(self, token: str, keyword: str, limit: int) -> list[Listing]:
        params = {
            "q": keyword,
            "limit": max(1, min(50, limit)),
            "filter": "itemLocationCountry:IT",
        }

        try:
            r = requests.get(
                self._browse_search_endpoint(),
                headers=self._headers(token),
                params=params,
                timeout=(6, 15),
            )
        except requests.exceptions.Timeout:
            if self.logger:
                self.logger.warning(f"[eBay] Browse timeout per '{keyword}'")
            return []
        except requests.RequestException as e:
            if self.logger:
                self.logger.warning(f"[eBay] Browse errore rete per '{keyword}': {e}")
            return []

        if r.status_code == 401:
            if self.logger:
                self.logger.warning("[eBay] Browse HTTP 401: token/credenziali non valide")
            self._token = None
            return []

        if r.status_code == 403:
            if self.logger:
                self.logger.warning(f"[eBay] Browse HTTP 403: controlla scopes/app access. {r.text[:220]}")
            return []

        if r.status_code != 200:
            if self.logger:
                self.logger.warning(f"[eBay] Browse HTTP {r.status_code}: {r.text[:220]}")
            return []

        try:
            data = r.json()
        except Exception:
            if self.logger:
                self.logger.warning(f"[eBay] Browse risposta non JSON: {r.text[:220]}")
            return []

        items = data.get("itemSummaries") or []
        listings = []
        seen_ids = set()

        for item in items:
            listing = self._listing_from_item(item)
            if not listing or listing.id in seen_ids:
                continue
            seen_ids.add(listing.id)
            listings.append(listing)

        if self.logger:
            total = data.get("total")
            self.logger.think(f"eBay Browse '{keyword}': {len(listings)} risultati letti / total={total}")

        return listings

    def search(self):
        token = self._get_access_token()
        if not token:
            if self.logger:
                self.logger.warning("[eBay] salto piattaforma: OAuth non configurato o fallito")
            return

        yielded = 0
        max_total = getattr(self.config, "max_total_items", None)
        max_per_kw = getattr(self.config, "max_items_per_keyword", 10)

        for idx, keyword in enumerate(self.config.search_keywords):
            if max_total is not None and yielded >= max_total:
                if self.logger:
                    self.logger.warning("Raggiunto max_total_items, interrompo eBay")
                return

            fetch_limit = max(10, min(50, max_per_kw * 4))
            listings = self._search_keyword(token, keyword, fetch_limit)

            produced_for_kw = 0

            for listing in listings:
                if produced_for_kw >= max_per_kw:
                    break
                if max_total is not None and yielded >= max_total:
                    if self.logger:
                        self.logger.warning("Raggiunto max_total_items, interrompo eBay")
                    return
                if self._already_seen(listing.id):
                    continue

                produced_for_kw += 1
                yielded += 1
                yield listing

            if idx < len(self.config.search_keywords) - 1:
                time.sleep(0.5)
