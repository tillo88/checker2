from __future__ import annotations

from .models import Listing, Evidence, Decision, DecisionStatus
from .filters import RuleFilter
from .scoring import ScoringEngine
from .decision import DecisionEngine
from spyengine.utils.images import image_url_to_b64


class ListingPipeline:
    def __init__(self, config, memory, ai_service, logger=None):
        self.config = config
        self.memory = memory
        self.ai = ai_service
        self.logger = logger
        self.rules = RuleFilter(config, logger)
        self.scoring = ScoringEngine(config, logger)
        self.decision = DecisionEngine(config, self.scoring, logger)

    def process(self, listing: Listing) -> Decision:
        evidence = Evidence()

        if self.memory.is_seen(listing.id):
            evidence.add("seen", DecisionStatus.SKIP, "Annuncio già visto")
            if self.logger:
                self.logger.decide("SKIP (già visto)")
            return Decision.skip("Già visto", evidence)

        if not self.rules.validate(listing, evidence):
            self.memory.mark_seen(listing.id)
            return self.decision.reject("Regole base fallite", evidence)

        config_name = "standard"

        ai_available = False
        if self.config.context_check_enabled:
            try:
                ai_available = self.ai.is_available()
            except Exception:
                ai_available = False

        if self.config.context_check_enabled and ai_available:
            if self.logger:
                self.logger.think("FASE 1: Context AI")
            ctx = self.ai.context_check(listing.title, listing.description or listing.title, self.config.item_description)
            evidence.add(
                "context",
                DecisionStatus.ACCEPT if ctx.sells_item else DecisionStatus.REJECT,
                ctx.reason,
                confidence=ctx.confidence,
                config=ctx.config,
                price_eur=ctx.price_eur,
            )
            if not ctx.sells_item:
                self.memory.mark_seen(listing.id)
                return self.decision.reject(f"Context: {ctx.reason}", evidence)
            if ctx.config:
                config_name = ctx.config
            if ctx.price_eur:
                listing.price = float(ctx.price_eur)
        elif self.config.context_check_enabled:
            evidence.add("context", DecisionStatus.SKIP, "Context AI abilitata ma llama non disponibile")
            if self.logger:
                self.logger.warning("Context AI saltata: llama non disponibile, uso filtri classici")

        detected = self.scoring.resolve_config(listing, evidence)
        if detected == "RIGETTATO":
            self.memory.mark_seen(listing.id)
            return self.decision.reject("Pattern di rigetto", evidence)
        if config_name == "standard" and detected != "standard":
            config_name = detected

        if not self.decision.check_budget(listing, config_name, evidence):
            self.memory.mark_seen(listing.id)
            return self.decision.reject("Prezzo sopra budget", evidence, config_name=config_name)

        score = self.scoring.score(listing, config_name, evidence)
        if score < 40:
            self.memory.mark_seen(listing.id)
            return self.decision.reject("Score troppo basso", evidence, score, config_name)

        if self.config.vision_enabled and listing.image_url:
            vision_available = False
            try:
                vision_available = self.ai.is_available()
            except Exception:
                vision_available = False

            if vision_available:
                if self.logger:
                    self.logger.think("FASE 3: Vision AI")
                b64 = image_url_to_b64(listing.image_url, logger=self.logger)
                if b64:
                    vision = self.ai.vision_check(b64, self.config.item_description, listing.title)
                    evidence.add(
                        "vision",
                        DecisionStatus.ACCEPT if vision.valid else DecisionStatus.REJECT,
                        vision.reason,
                        confidence=vision.confidence,
                    )
                    if not vision.valid:
                        self.memory.mark_seen(listing.id)
                        return self.decision.reject(f"Vision: {vision.reason}", evidence, score, config_name)
            else:
                evidence.add("vision", DecisionStatus.SKIP, "Vision AI abilitata ma llama non disponibile")

        decision = self.decision.accept(listing, evidence, score, config_name)
        self.memory.mark_seen(listing.id)
        self.memory.register_price(listing.price, config_name)
        return decision
