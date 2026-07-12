from __future__ import annotations
from spyengine.core.models import SpyConfig
from .base import BasePlatform
from .mock import MockPlatform
from .vinted import VintedPlatform
from .subito import SubitoPlatform
from .ebay import EbayPlatform
from .wallapop import WallapopPlatform


PLATFORMS = {
    "MOCK": MockPlatform,
    "VINTED": VintedPlatform,
    "SUBITO": SubitoPlatform,
    "EBAY": EbayPlatform,
    "WALLAPOP": WallapopPlatform,
}


class PlatformRegistry:
    @staticmethod
    def create_enabled(names: list[str], config: SpyConfig, logger=None, browser=None, memory=None) -> list[BasePlatform]:
        out = []
        for name in names:
            cls = PLATFORMS.get(str(name).upper())
            if not cls:
                if logger:
                    logger.warning(f"Piattaforma sconosciuta: {name}")
                continue
            out.append(cls(config, logger=logger, browser=browser, memory=memory))
        return out
