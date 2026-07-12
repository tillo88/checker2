from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FactCheckIssue:
    severity: str
    key: str
    message: str
    family_id: int | None = None
    variant_id: int | None = None
    listing_id: int | None = None


AUTHORITATIVE_SOURCE_PROFILES = {
    "technology_gpu": ["TechPowerUp", "NVIDIA", "AMD", "VideoCardz", "partner_datasheet"],
    "technology_monitor": ["TFTCentral", "RTINGS", "DisplaySpecifications", "Panelook", "manufacturer"],
    "technology_cpu": ["Intel", "AMD", "CPU-World", "manufacturer"],
    "technology_storage": ["manufacturer", "TechPowerUp", "AnandTech"],
    "technology_ram": ["manufacturer", "QVL", "Kingston", "Corsair", "Crucial", "Samsung"],
    "technology_phone": ["manufacturer", "GSMArena", "retail_catalog"],
}


def authoritative_sources_for(category: str) -> list[str]:
    return list(AUTHORITATIVE_SOURCE_PROFILES.get(category, ["manufacturer", "trusted_catalog"]))


def check_variant_conflicts(store, *, category: str | None = None, limit: int = 200) -> list[FactCheckIssue]:
    """Detect simple intra-family spec conflicts.

    This does not replace authoritative web verification. It flags suspicious
    marketplace-derived facts so a later trusted-source resolver can confirm.
    """
    where = ""
    params: list[Any] = []
    if category:
        where = "WHERE pf.category=?"
        params.append(category)
    rows = store.conn.execute(
        f"""
        SELECT pf.id AS family_id, pf.category, pf.family_name, pv.id AS variant_id, pv.variant_name,
               sf.spec_key, sf.spec_value_json, sf.source, sf.confidence
        FROM spec_facts sf
        JOIN product_variants pv ON pv.id = sf.variant_id
        JOIN product_families pf ON pf.id = pv.family_id
        {where}
        ORDER BY pf.id, sf.spec_key, sf.confidence DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()

    by_family_key: dict[tuple[int, str], list[dict]] = {}
    for row in rows:
        item = dict(row)
        try:
            item["value"] = json.loads(item.pop("spec_value_json"))
        except Exception:
            item["value"] = None
        by_family_key.setdefault((int(item["family_id"]), item["spec_key"]), []).append(item)

    issues: list[FactCheckIssue] = []
    for (family_id, spec_key), facts in by_family_key.items():
        values = sorted({str(f.get("value")) for f in facts if f.get("value") is not None})
        if len(values) <= 1:
            continue
        family_name = facts[0].get("family_name") or ""
        category_name = facts[0].get("category") or ""
        # Some dimensions are expected variants, not conflicts.
        if category_name == "technology_gpu" and spec_key == "vram_gb":
            # Expected variant dimension. Still useful to mark family as multi-variant.
            continue
        if category_name == "technology_ram" and spec_key in {"module_capacity_gb", "module_count"}:
            continue
        issues.append(
            FactCheckIssue(
                "warning",
                f"conflicting_{spec_key}",
                f"{family_name}: valori diversi per {spec_key}: {', '.join(values)}",
                family_id=family_id,
            )
        )
    return issues


def check_claim_against_family(store, *, family_id: int, spec_key: str, claimed_value: Any) -> FactCheckIssue | None:
    rows = store.conn.execute(
        """
        SELECT DISTINCT spec_value_json FROM spec_facts
        WHERE family_id=? AND spec_key=?
        """,
        (family_id, spec_key),
    ).fetchall()
    known = set()
    for row in rows:
        try:
            known.add(json.loads(row[0]))
        except Exception:
            pass
    if not known:
        return None
    if claimed_value in known:
        return None
    return FactCheckIssue(
        "warning",
        f"unknown_variant_{spec_key}",
        f"Valore dichiarato {claimed_value!r} non presente tra varianti note {sorted(known)!r}",
        family_id=family_id,
    )
