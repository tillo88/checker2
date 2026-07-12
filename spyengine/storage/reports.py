from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime


class DecisionReporter:
    def __init__(self, spy_name: str, data_dir: str = "data", *, enabled: bool = True):
        self.spy_name = spy_name
        self.enabled = bool(enabled)
        self.dir = Path(data_dir) / "reports" / spy_name
        if self.enabled:
            self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, listing, decision) -> Path | None:
        if not self.enabled:
            return None
        safe_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in listing.id)
        path = self.dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_id}.json"

        payload = {
            "listing": {
                "id": listing.id,
                "platform": listing.platform,
                "title": listing.title,
                "price": listing.price,
                "url": listing.url,
                "description": listing.description,
                "image_url": listing.image_url,
                "extra_info": listing.extra_info,
            },
            "decision": {
                "status": decision.status.value,
                "reason": decision.reason,
                "score": decision.score,
                "config": decision.config,
            },
            "evidence": [
                {
                    "step": e.step,
                    "status": e.status,
                    "reason": e.reason,
                    "score_delta": e.score_delta,
                    "confidence": e.confidence,
                    "data": e.data,
                    "timestamp": e.timestamp,
                }
                for e in decision.evidence.items
            ],
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
