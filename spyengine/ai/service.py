from __future__ import annotations

import threading
import time
from typing import Optional

from spyengine.core.models import ContextResult, VisionResult
from spyengine.utils.text import extract_json_object
from .ollama_queue import OllamaQueue


class AIService:
    def __init__(self, queue: OllamaQueue, system_prompt: str, logger=None):
        self.queue = queue
        self.system_prompt = system_prompt
        self.logger = logger
        self._last_health_check = 0.0
        self._last_health_value = False
        self._health_ttl = 15.0

    def is_available(self) -> bool:
        now = time.time()
        if now - self._last_health_check < self._health_ttl:
            return self._last_health_value

        self._last_health_check = now
        self._last_health_value = bool(self.queue.is_healthy())
        return self._last_health_value

    def context_check(self, title: str, description: str, item_desc: str, image_b64: Optional[str] = None) -> ContextResult:
        if not self.is_available():
            return ContextResult(False, "Context OFF", confidence=0)

        description_short = (description or "")[:2200]

        prompt = f"""{self.system_prompt}

[TASK]
Analizza questo annuncio marketplace. L'utente cerca strettamente:
{item_desc}

Titolo annuncio:
{title}

Descrizione annuncio:
{description_short}

Protocollo fisso:
- Valuta il contenuto reale dell'annuncio, non fidarti di tag SEO o keyword messe per attirare ricerche.
- sells_item=true solo se l'annuncio vende davvero il target richiesto o un componente separabile chiaramente acquistabile.
- Per bundle, lotti, PC/computer interi o kit: sells_item=true solo se il target è vendibile separatamente, smembrabile, o il prezzo del target è inferibile con buona confidenza.
- Rifiuta accessori, servizi, riparazioni, scatole vuote, ricambi non funzionanti o varianti incompatibili.
- Estrai la configurazione più utile per il motore, per esempio capacità, quantità, modello, taglia o variante.
- Estrai price_eur del target se chiaro. Se l'annuncio è un kit e il prezzo unitario è ricavabile, usa il prezzo più utile per il target; altrimenti lascia il prezzo totale e spiega in reason.
- Non applicare sconti, tolleranze o budget di tua iniziativa: il motore applica il budget numerico dopo la tua risposta.
- Se il testo è ambiguo ma plausibile, usa confidence 60-75 e spiega il dubbio in reason.
- Se il testo contraddice il target, usa sells_item=false anche se contiene keyword utili.

Rispondi SOLO con JSON valido:
{{"sells_item":true/false, "config":"...", "price_eur":number_or_null, "confidence":0-100, "reason":"max 18 parole"}}

JSON:"""

        event = threading.Event()
        result = {"value": ContextResult(False, "Context inconclusivo", confidence=0)}

        def callback(resp, err):
            if err:
                result["value"] = ContextResult(False, f"Context error: {err}", confidence=0)
            else:
                data = extract_json_object(resp)
                if not data:
                    result["value"] = ContextResult(False, "Context parse failed", confidence=0)
                else:
                    conf = int(data.get("confidence", 0) or 0)
                    result["value"] = ContextResult(
                        sells_item=bool(data.get("sells_item", False)) and conf >= 60,
                        reason=str(data.get("reason", "")),
                        config=data.get("config"),
                        price_eur=data.get("price_eur"),
                        confidence=conf,
                    )
            event.set()

        self.queue.submit(
            prompt,
            images=[image_b64] if image_b64 else None,
            priority=OllamaQueue.PRIORITY_CONTEXT,
            timeout=60,
            callback=callback,
        )

        return result["value"] if event.wait(timeout=75) else ContextResult(False, "Context timeout", confidence=0)

    def vision_check(self, image_b64: str, item_desc: str, title: str = "") -> VisionResult:
        if not self.is_available():
            return VisionResult(True, "Vision OFF", confidence=0)

        prompt = f"""{self.system_prompt}

[TASK]
Analizza l'immagine di un annuncio marketplace.

Target utente:
{item_desc}

Titolo/contesto annuncio:
{title}

Protocollo fisso:
- valid=true solo se l'immagine è compatibile col target richiesto.
- valid=false se mostra chiaramente un prodotto incompatibile, accessorio, scatola vuota, laptop/PC completo non pertinente o variante esclusa.
- Se l'immagine è poco chiara ma non contraddice il target, usa valid=true con bassa confidence.
- Non decidere per prezzo o budget dalla foto.

Rispondi SOLO con JSON valido:
{{"valido": true/false, "motivo": "max 15 parole", "confidence": 0-100}}

JSON:"""

        event = threading.Event()
        result = {"value": VisionResult(True, "Vision inconclusiva", confidence=0)}

        def callback(resp, err):
            if err:
                result["value"] = VisionResult(True, f"Vision error: {err}", confidence=0)
            else:
                data = extract_json_object(resp)
                if not data:
                    result["value"] = VisionResult(True, "Vision parse failed", confidence=0)
                else:
                    result["value"] = VisionResult(
                        valid=bool(data.get("valido", data.get("valid", data.get("correct", True)))),
                        reason=str(data.get("motivo", data.get("reason", ""))),
                        confidence=int(data.get("confidence", 0) or 0),
                    )
            event.set()

        self.queue.submit(
            prompt,
            images=[image_b64],
            priority=OllamaQueue.PRIORITY_VISION,
            timeout=60,
            callback=callback,
        )

        return result["value"] if event.wait(timeout=75) else VisionResult(True, "Vision timeout", confidence=0)
