from __future__ import annotations

import re
from statistics import median
from typing import Any


def _comparison_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def score_opportunity_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add a price opportunity score without altering classification confidence."""
    groups: dict[tuple[str, ...], list[float]] = {}
    row_keys: dict[int, list[tuple[str, tuple[str, ...], int, float]]] = {}

    for row in rows:
        price = float(row.get("price") or 0.0)
        if price <= 0:
            continue
        category = _comparison_text(row.get("category"))
        brand = _comparison_text(row.get("brand"))
        model = _comparison_text(row.get("model"))
        title = _comparison_text(row.get("title"))
        candidates: list[tuple[str, tuple[str, ...], int, float]] = []
        if category and brand and model:
            candidates.append(("model", ("model", category, brand, model), 3, 1.0))
        if category and title:
            candidates.append(("resolved_title", ("title", category, title), 3, 0.9))
        row_keys[id(row)] = candidates
        for _, key, _, _ in candidates:
            groups.setdefault(key, []).append(price)

    scored: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        price = float(row.get("price") or 0.0)
        reference: tuple[str, list[float], float] | None = None
        for scope, key, minimum, strength in row_keys.get(id(original), []):
            samples = groups.get(key, [])
            if len(samples) >= minimum:
                reference = (scope, samples, strength)
                break

        if not reference or price <= 0:
            row.update(
                {
                    "opportunity_score": None,
                    "opportunity_status": "insufficient_data",
                    "reference_price": None,
                    "discount_percent": None,
                    "reference_scope": "insufficient_data",
                    "reference_sample_size": 0,
                    "reference_confidence": 0.0,
                }
            )
        else:
            scope, samples, strength = reference
            reference_price = float(median(samples))
            discount_percent = (
                ((reference_price - price) / reference_price) * 100.0
                if reference_price > 0
                else 0.0
            )
            reference_confidence = min(
                1.0, strength * (0.55 + 0.075 * min(len(samples), 6))
            )
            if discount_percent > 65.0:
                status = "suspicious_low_price"
                score = max(0.0, 35.0 - (discount_percent - 65.0) * 0.5)
            else:
                score = max(
                    0.0, min(100.0, 50.0 + discount_percent * 0.9 * strength)
                )
                if discount_percent >= 10.0:
                    status = "good_value"
                elif discount_percent <= -10.0:
                    status = "above_reference"
                else:
                    status = "near_reference"
            row.update(
                {
                    "opportunity_score": round(score, 1),
                    "opportunity_status": status,
                    "reference_price": round(reference_price, 2),
                    "discount_percent": round(discount_percent, 1),
                    "reference_scope": scope,
                    "reference_sample_size": len(samples),
                    "reference_confidence": round(reference_confidence, 3),
                }
            )
        scored.append(row)

    return sorted(
        scored,
        key=lambda row: (
            row.get("opportunity_score") is not None,
            float(row.get("opportunity_score") or -1.0),
            float(row.get("confidence") or 0.0),
        ),
        reverse=True,
    )
