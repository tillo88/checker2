from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Iterable
from spyengine.core.models import Listing, SpyConfig


class BasePlatform(ABC):
    name: str = "BASE"

    def __init__(self, config: SpyConfig, logger=None, browser=None, memory=None):
        self.config = config
        self.logger = logger
        self.browser = browser
        self.memory = memory

    @abstractmethod
    def search(self) -> Iterable[Listing]:
        raise NotImplementedError

    def _already_seen(self, listing_id: str) -> bool:
        return bool(self.memory and self.memory.is_seen(listing_id))
