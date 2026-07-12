from __future__ import annotations

import re

from .models import SpyConfig, Listing, Evidence, DecisionStatus
from spyengine.utils.text import normalize_text


def _contains_term(text: str, term: str) -> bool:
    """
    Matching sicuro:
    - "32 gb" matcha "32gb" e viceversa
    - "8gb" matcha "RAM DDR4 8GB"
    - "8gb" NON matcha "128GB"
    - parole corte tipo "pc" matchano come parola intera
    """
    text = normalize_text(text)
    term = normalize_text(term)

    if not term:
        return False

    compact_term = term.replace(" ", "")

    # Capacità/dimensioni: matcha sul testo con spazi, non sul testo compattato.
    # Così "ddr4 8gb" funziona, ma "128gb" non matcha "8gb".
    cap_match = re.fullmatch(r"(\d+)(gb|tb|mb|g|t|m)", compact_term)
    if cap_match:
        number, unit = cap_match.groups()
        return re.search(rf"(?<!\d){re.escape(number)}\s*{re.escape(unit)}(?![a-z0-9])", text) is not None

    # Pattern tipo 2x32gb / 1x16gb.
    mult_match = re.fullmatch(r"(\d+)x(\d+)(gb|tb|mb|g|t|m)", compact_term)
    if mult_match:
        qty, number, unit = mult_match.groups()
        return re.search(
            rf"(?<![a-z0-9]){re.escape(qty)}\s*x\s*{re.escape(number)}\s*{re.escape(unit)}(?![a-z0-9])",
            text,
        ) is not None

    compact_text = text.replace(" ", "")
    if compact_term and compact_term in compact_text:
        return True

    if " " in term:
        return term in text

    if len(term) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None

    return term in text


class RuleFilter:
    def __init__(self, config: SpyConfig, logger=None):
        self.config = config
        self.logger = logger
        self.exclude = [normalize_text(w) for w in config.exclude_words]
        self.required = [normalize_text(w) for w in config.required_words]
        self.required_groups = [
            [normalize_text(w) for w in group if normalize_text(w)]
            for group in getattr(config, "required_groups", []) or []
            if isinstance(group, list)
        ]
        self.distractors = [normalize_text(w) for w in config.distractor_words]

    def validate(self, listing: Listing, evidence: Evidence) -> bool:
        full = normalize_text(listing.full_text)

        # Hard exclusions first.
        found_excluded = [w for w in self.exclude if _contains_term(full, w)]
        if found_excluded:
            reason = f"Parole escluse: {found_excluded}"
            evidence.add("rules", DecisionStatus.REJECT, reason)
            if self.logger:
                self.logger.think(reason)
            return False

        # New strict groups: every group must have at least one matched alternative.
        # Example: [["ddr4"], ["ram", "memoria"], ["32gb", "16gb"]]
        for group in self.required_groups:
            matched = [w for w in group if _contains_term(full, w)]
            if not matched:
                reason = f"Manca gruppo richiesto: {group}"
                evidence.add("rules", DecisionStatus.REJECT, reason, required_group=group)
                if self.logger:
                    self.logger.think(reason)
                return False
            evidence.add("rules", "MATCH", f"Gruppo richiesto OK: {matched}", required_group=group)

        # Legacy required_words remains OR for backwards compatibility.
        # Use required_groups for hard AND/OR logic.
        if self.required and not self.required_groups:
            found_required = [w for w in self.required if _contains_term(full, w)]
            if not found_required:
                reason = f"Manca parola richiesta: {self.required}"
                evidence.add("rules", DecisionStatus.REJECT, reason)
                if self.logger:
                    self.logger.think(reason)
                return False
            evidence.add("rules", "MATCH", f"Parole richieste trovate: {found_required}")

        found_distractors = [w for w in self.distractors if _contains_term(full, w)]
        if found_distractors:
            # With AI enabled, distractors should trigger context review, not hard reject.
            # This is important for bundles/PC completi that might be smembrabili.
            evidence.add("rules", "DISTRACTOR", f"Distrattori da verificare con AI: {found_distractors}")
            if self.logger:
                self.logger.think(f"Distrattori da verificare con AI: {found_distractors}")
            if not getattr(self.config, "context_check_enabled", True):
                evidence.add("rules", DecisionStatus.REJECT, f"Distrattori: {found_distractors}")
                return False

        evidence.add("rules", DecisionStatus.ACCEPT, "Regole base OK")
        return True
