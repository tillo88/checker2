from __future__ import annotations

import re
from typing import Any


COMMERCIAL_UNIT_WORDS = {
    "banco", "banchi", "modulo", "moduli", "stick", "pezzo", "pezzi", "pz",
    "kit", "set", "coppia", "paio", "unità", "unita", "cad", "cadauno",
}

TECHNICAL_UNIT_CONTEXTS = {
    "vram": "technology_gpu",
    "gddr": "technology_gpu",
    "hz": "technology_monitor",
    "volt": "tools_battery",
    "v": "tools_battery",
    "gb": "technical_capacity",
}


def validate_product_analysis(text: str, analysis: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    tl = str(text or "").lower()
    category = analysis.get("category") or "unknown"
    specs = analysis.get("variant_specs") or {}

    # Guardrail: VRAM GB is a GPU technical spec, never a commercial unit count.
    if category == "technology_gpu":
        if re.search(r"\b(vram|gddr)\b", tl) and re.search(r"\b(banco|banchi|modulo|moduli|stick)\b", tl):
            warnings.append("gpu_vram_not_ram_module: VRAM è specifica tecnica GPU, non banchi/moduli RAM")
        if specs.get("vram_gb") and int(specs["vram_gb"]) > 128:
            warnings.append("gpu_vram_unusually_high")

    # RAM: banks/modules make sense here, but VRAM does not.
    if category == "technology_ram" and "vram" in tl:
        warnings.append("ram_listing_mentions_vram_check_category")

    # Generic contradiction: kit/set/pezzi are commercial quantity, not technical specs.
    if re.search(r"\bkit\s+da\s+(\d+)\b", tl) and category.startswith("technology_"):
        m = re.search(r"\bkit\s+da\s+(\d+)\b", tl)
        if m and int(m.group(1)) > 8 and category == "technology_gpu":
            warnings.append("gpu_large_kit_quantity_check_bundle")

    if analysis.get("ambiguity_status") == "variant_ambiguous":
        warnings.append("variant_ambiguous_requires_listing_or_authoritative_check")

    return warnings
