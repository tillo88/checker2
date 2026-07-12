from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse
import hashlib
import re


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


@dataclass(frozen=True)
class HarvestListing:
    """Normalized listing card stored by the nightly harvester.

    This is intentionally generic. Marketplace-specific adapters can add
    source-specific fields to raw/specs without changing the DB schema.
    """

    source: str
    title: str
    url: str = ""
    external_id: str = ""
    price: float | None = None
    currency: str = ""
    location: str = ""
    seller: str = ""
    condition: str = ""
    image_url: str = ""
    category: str = ""
    query: str = ""
    specs: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def normalized_title(self) -> str:
        return _clean_text(self.title).lower()

    def normalized_url(self) -> str:
        url = _clean_text(self.url)
        if not url:
            return ""
        parsed = urlparse(url)
        # Drop tracking/query/fragment so the same ad does not duplicate.
        return parsed._replace(query="", fragment="").geturl()

    def fingerprint(self) -> str:
        stable = self.external_id or self.normalized_url()
        if not stable:
            stable = "|".join(
                [
                    self.source,
                    self.normalized_title(),
                    str(self.price or ""),
                    _clean_text(self.location).lower(),
                ]
            )
        return hashlib.sha1(f"{self.source}|{stable}".encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceDefinition:
    """Registry metadata for one source.

    status:
      - enabled: reasonably safe/default public collector
      - experimental: public collector exists, but must be enabled explicitly
      - manual: import/manual-only path
      - disabled: intentionally not scraped automatically
    """

    name: str
    label: str
    group: str
    countries: tuple[str, ...] = ()
    status: str = "experimental"
    default_enabled: bool = False
    requires_login: bool = False
    robots_respected: bool = True
    search_url_templates: tuple[str, ...] = ()
    notes: str = ""

    def build_urls(self, query: str, *, limit: int = 100) -> list[str]:
        from urllib.parse import quote_plus

        encoded = quote_plus(query)
        urls: list[str] = []
        for template in self.search_url_templates:
            urls.append(
                template.format(
                    query=encoded,
                    q=encoded,
                    raw_query=query,
                    limit=limit,
                )
            )
        return urls
