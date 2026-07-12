from __future__ import annotations

from collections.abc import Iterable

from spyengine.core.models import Listing

from .base import BasePlatform


class MockPlatform(BasePlatform):
    """Deterministic offline platform used for smoke tests and safe demos."""

    name = "MOCK"

    def search(self) -> Iterable[Listing]:
        keywords = self.config.search_keywords or [self.config.item_description or "prodotto"]
        limit = max(1, int(self.config.max_items_per_keyword or 1))
        emitted = 0

        for index, keyword in enumerate(keywords, start=1):
            if emitted >= limit:
                break
            listing_id = f"mock-{self.config.name}-{index}"
            if self._already_seen(listing_id):
                continue
            emitted += 1
            yield Listing(
                id=listing_id,
                platform=self.name,
                title=f"{keyword} demo verificabile",
                price=99.0 + index,
                url=f"https://example.invalid/mock/{listing_id}",
                description="Annuncio sintetico offline per test della pipeline SpyEngine.",
                raw={"mock": True, "keyword": keyword},
            )
