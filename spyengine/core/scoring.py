from __future__ import annotations

import re

from .models import SpyConfig, Listing, Evidence, DecisionStatus
from spyengine.utils.text import normalize_text


def _term_pattern(term: str) -> str:
    """
    Regex permissiva per termini normalizzati:
    - "32 gb" matcha anche "32gb"
    - "g.skill" resta sicuro
    """
    term = normalize_text(term)
    if not term:
        return ""
    parts = [re.escape(p) for p in re.split(r"\s+", term) if p]
    return r"\s*".join(parts)


def _contains_term(text: str, term: str) -> bool:
    text_n = normalize_text(text)
    term_n = normalize_text(term)
    if not term_n:
        return False

    compact_term = term_n.replace(" ", "")

    # Capacità/dimensioni: "8gb" deve matchare "DDR4 8GB" ma non "128GB".
    cap_match = re.fullmatch(r"(\d+)(gb|tb|mb|g|t|m)", compact_term)
    if cap_match:
        number, unit = cap_match.groups()
        return re.search(rf"(?<!\d){re.escape(number)}\s*{re.escape(unit)}(?![a-z0-9])", text_n) is not None

    compact_text = text_n.replace(" ", "")
    if compact_term and compact_term in compact_text:
        return True

    return term_n in text_n


def _extract_quantity_for_term(text: str, term: str, aliases: list[str] | None = None) -> tuple[int, str, bool]:
    """
    Generic quantity detector.

    Works with:
    - 2x32gb / 2 x 32 gb / 2×32gb
    - 32gb x2
    - 4 sedie / 4 gomme if term or alias is "sedie"/"gomme"

    Returns: quantity, reason, explicit_quantity_found
    """
    aliases = aliases or []
    quantity = 1
    reason = "quantità non esplicita, assumo 1 unità"
    explicit = False

    terms = [term] + aliases
    for raw_term in terms:
        pat = _term_pattern(raw_term)
        if not pat:
            continue

        patterns = [
            rf"(?<![a-z0-9])(\d{{1,3}})\s*[x×]\s*{pat}(?![a-z0-9])",
            rf"(?<![a-z0-9]){pat}\s*[x×]\s*(\d{{1,3}})(?![a-z0-9])",
            rf"(?<![a-z0-9])(\d{{1,3}})\s+{pat}(?![a-z0-9])",
        ]

        for rx in patterns:
            m = re.search(rx, text)
            if not m:
                continue
            try:
                q = int(m.group(1))
            except Exception:
                continue
            if q > 0:
                quantity = max(1, min(q, 999))
                reason = f"quantità {quantity} rilevata da '{m.group(0).strip()}'"
                explicit = True
                return quantity, reason, explicit

    return quantity, reason, explicit


class ScoringEngine:
    def __init__(self, config: SpyConfig, logger=None):
        self.config = config
        self.logger = logger

    def resolve_config(self, listing: Listing, evidence: Evidence) -> str:
        full = normalize_text(listing.full_text)
        for pat in self.config.reject_patterns:
            if normalize_text(pat) in full:
                evidence.add("pattern", DecisionStatus.REJECT, f"Pattern rigetto: {pat}")
                return "RIGETTATO"
        for name, patterns in self.config.config_patterns.items():
            for pat in patterns:
                if normalize_text(pat) in full:
                    evidence.add("pattern", DecisionStatus.ACCEPT, f"Config {name}: {pat}", confidence=85)
                    return name
        evidence.add("pattern", DecisionStatus.ACCEPT, "Nessun pattern specifico, uso standard", confidence=70)
        return "standard"

    def resolve_budget(self, config_name: str) -> float:
        if config_name in self.config.budget:
            return self.config.budget[config_name]
        for k, v in self.config.budget.items():
            if k.lower() in config_name.lower():
                return v
        return self.config.budget.get("standard", max(self.config.budget.values()) if self.config.budget else 999.0)

    def resolve_unit_budget(self, listing: Listing, evidence: Evidence | None = None) -> dict | None:
        rules = getattr(self.config, "unit_budget_rules", []) or []
        if not rules:
            return None

        text = normalize_text(listing.full_text)
        candidates: list[dict] = []

        for rule in rules:
            if not isinstance(rule, dict):
                continue

            terms = rule.get("match") or rule.get("matches") or rule.get("terms") or []
            if isinstance(terms, str):
                terms = [terms]
            if not isinstance(terms, list):
                continue

            try:
                max_unit = float(rule.get("max_price_per_unit", rule.get("max_unit_price", rule.get("budget_per_unit"))))
            except Exception:
                continue
            if max_unit <= 0:
                continue

            aliases = rule.get("unit_aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            aliases = [str(x) for x in aliases if str(x).strip()] if isinstance(aliases, list) else []

            matched_terms = []
            best_qty = 1
            best_reason = "quantità non esplicita, assumo 1 unità"
            explicit_qty = False

            for term in terms:
                term = str(term).strip()
                if not term or not _contains_term(text, term):
                    continue
                matched_terms.append(term)

                qty, reason, explicit = _extract_quantity_for_term(text, term, aliases)
                if explicit and (not explicit_qty or qty > best_qty):
                    best_qty = qty
                    best_reason = reason
                    explicit_qty = True

            if not matched_terms:
                continue

            total_budget = max_unit * best_qty
            candidates.append(
                {
                    "name": str(rule.get("name") or matched_terms[0]),
                    "matched_terms": matched_terms,
                    "quantity": best_qty,
                    "max_price_per_unit": max_unit,
                    "total_budget": total_budget,
                    "unit": str(rule.get("unit") or "unit"),
                    "quantity_reason": best_reason,
                    "explicit_quantity": explicit_qty,
                    "priority": (1 if explicit_qty else 0, len(matched_terms), -total_budget),
                }
            )

        if not candidates:
            return None

        # Prefer rules where a quantity was explicitly detected; then more matched terms; then stricter total budget.
        candidates.sort(key=lambda x: x["priority"], reverse=True)
        best = candidates[0]

        if evidence is not None:
            evidence.add(
                "unit_budget",
                DecisionStatus.ACCEPT,
                (
                    f"{best['name']}: {best['quantity']} x "
                    f"{best['max_price_per_unit']:.0f}EUR/{best['unit']} = budget {best['total_budget']:.0f}EUR "
                    f"({best['quantity_reason']})"
                ),
                **best,
            )

        return best

    def resolve_effective_budget(self, listing: Listing, config_name: str, evidence: Evidence | None = None) -> tuple[float, dict | None]:
        unit = self.resolve_unit_budget(listing, evidence)
        if unit:
            return float(unit["total_budget"]), unit
        return self.resolve_budget(config_name), None

    def score(self, listing: Listing, config_name: str, evidence: Evidence) -> int:
        text = normalize_text(listing.title)
        score = 70
        for brand in self.config.premium_brands:
            if normalize_text(brand) in text:
                score += 5
                evidence.add("score", "BONUS", f"Marca premium: {brand}", score_delta=5)
                break
        for kw, bonus in self.config.positive_keywords.items():
            if normalize_text(kw) in text:
                score += int(bonus)
                evidence.add("score", "BONUS", f"Keyword positiva: {kw}", score_delta=int(bonus))
        for kw in self.config.negative_keywords:
            if normalize_text(kw) in text:
                score -= 20
                evidence.add("score", "MALUS", f"Keyword negativa: {kw}", score_delta=-20)

        budget, unit = self.resolve_effective_budget(listing, config_name, evidence=None)
        if budget > 0:
            ratio = listing.price / budget
            if ratio <= 0.5:
                score += 10
            elif ratio <= 0.7:
                score += 5
            elif ratio <= 0.9:
                score += 2
            elif ratio >= 1.0:
                score -= 15

        final = max(0, min(100, score))
        evidence.add("score", DecisionStatus.ACCEPT, f"Score finale {final}/100")
        return final
