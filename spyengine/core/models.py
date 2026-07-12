from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class DecisionStatus(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    SKIP = "SKIP"
    UNCERTAIN = "UNCERTAIN"


@dataclass(slots=True)
class Listing:
    id: str
    platform: str
    title: str
    price: float
    url: str
    description: str = ""
    image_url: Optional[str] = None
    extra_info: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return f"{self.title}\n{self.description}".strip()


@dataclass(slots=True)
class EvidenceItem:
    step: str
    status: str
    reason: str = ""
    score_delta: int = 0
    confidence: Optional[float] = None
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class Evidence:
    items: list[EvidenceItem] = field(default_factory=list)

    def add(self, step: str, status, reason: str = "", score_delta: int = 0, confidence: Optional[float] = None, **data: Any) -> None:
        value = status.value if hasattr(status, "value") else str(status)
        self.items.append(EvidenceItem(str(step), value, reason, score_delta, confidence, data))

    def reasons(self) -> list[str]:
        return [i.reason for i in self.items if i.reason]


@dataclass(slots=True)
class ContextResult:
    sells_item: bool
    reason: str
    config: Optional[str] = None
    price_eur: Optional[float] = None
    confidence: int = 0


@dataclass(slots=True)
class VisionResult:
    valid: bool
    reason: str
    confidence: int = 0


@dataclass(slots=True)
class Decision:
    status: DecisionStatus
    reason: str
    score: int = 0
    config: str = "standard"
    evidence: Evidence = field(default_factory=Evidence)

    @classmethod
    def accept(cls, reason: str, score: int, config: str, evidence: Evidence) -> "Decision":
        return cls(DecisionStatus.ACCEPT, reason, score, config, evidence)

    @classmethod
    def reject(cls, reason: str, evidence: Evidence, score: int = 0, config: str = "standard") -> "Decision":
        return cls(DecisionStatus.REJECT, reason, score, config, evidence)

    @classmethod
    def skip(cls, reason: str, evidence: Evidence) -> "Decision":
        return cls(DecisionStatus.SKIP, reason, 0, "standard", evidence)


@dataclass
class SpyConfig:
    name: str
    item_description: str
    search_keywords: list[str]
    exclude_words: list[str]
    required_words: list[str]
    distractor_words: list[str]
    budget: dict[str, float]
    config_patterns: dict[str, list[str]]
    reject_patterns: list[str]
    premium_brands: list[str]
    positive_keywords: dict[str, int]
    negative_keywords: list[str]
    platforms: list[str]
    unit_budget_rules: list[dict[str, Any]] = field(default_factory=list)
    required_groups: list[list[str]] = field(default_factory=list)
    vision_enabled: bool = True
    context_check_enabled: bool = True
    interval_seconds: int = 300
    max_history: int = 200
    ebay_app_id_env: str = "EBAY_APP_ID"
    max_items_per_keyword: int = 10
    max_total_items: int = 0
    fetch_details: bool = True
    debug_snapshots: bool = False
    debug_dir: str = "data/debug"
    system_prompt: str = "[SYSTEM]\nYou are a strict JSON generator. Output ONLY valid JSON."
