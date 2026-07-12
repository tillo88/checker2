from __future__ import annotations
from .models import Decision, DecisionStatus, Evidence, Listing, SpyConfig
from .scoring import ScoringEngine


class DecisionEngine:
    def __init__(self, config: SpyConfig, scoring: ScoringEngine, logger=None):
        self.config = config
        self.scoring = scoring
        self.logger = logger

    def reject(self, reason: str, evidence: Evidence, score: int = 0, config_name: str = "standard") -> Decision:
        evidence.add("decision", DecisionStatus.REJECT, reason)
        if self.logger:
            self.logger.decide("RIFIUTO", reason)
        return Decision.reject(reason, evidence, score, config_name)

    def accept(self, listing: Listing, evidence: Evidence, score: int, config_name: str) -> Decision:
        reason = f"{listing.platform} | {listing.price:.0f}EUR | Score {score}/100 | {config_name}"
        evidence.add("decision", DecisionStatus.ACCEPT, reason)
        if self.logger:
            self.logger.decide("NOTIFICO", reason)
        return Decision.accept(reason, score, config_name, evidence)

    def check_budget(self, listing: Listing, config_name: str, evidence: Evidence) -> bool:
        budget, unit = self.scoring.resolve_effective_budget(listing, config_name, evidence=evidence)
        ok = listing.price <= budget

        if unit:
            reason = (
                f"{listing.price:.0f}EUR / unit budget {budget:.0f}EUR "
                f"({unit['quantity']} x {unit['max_price_per_unit']:.0f}EUR/{unit['unit']})"
            )
        else:
            reason = f"{listing.price:.0f}EUR / budget {budget:.0f}EUR"

        evidence.add(
            "budget",
            DecisionStatus.ACCEPT if ok else DecisionStatus.REJECT,
            reason,
            budget=budget,
            unit_budget=unit,
        )
        return ok
