from __future__ import annotations

import re
from typing import Any


DEFAULT_PLATFORMS = ["VINTED", "SUBITO", "EBAY", "WALLAPOP"]


def clean(value: Any) -> str:
    s = str(value or "").lower()
    s = s.replace("×", "x")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def dedup(values: list[Any], limit: int = 40) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        s = clean(value)
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def add_terms(out: dict, key: str, terms: list[str], limit: int = 40) -> None:
    out[key] = dedup(as_list(out.get(key)) + terms, limit)


def remove_terms(out: dict, key: str, terms: set[str]) -> list[str]:
    vals = as_list(out.get(key))
    removed = []
    kept = []
    for value in vals:
        s = clean(value)
        if s in terms:
            removed.append(s)
        else:
            kept.append(value)
    out[key] = dedup(kept, 40)
    return removed


def text_blob(out: dict, user_description: str = "") -> str:
    parts = [user_description, out.get("name", ""), out.get("item_description", ""), out.get("system_prompt", "")]
    for key in ["search_keywords", "required_words", "exclude_words", "distractor_words", "reject_patterns"]:
        parts.extend(str(x) for x in as_list(out.get(key)))
    return clean(" ".join(str(x) for x in parts))


def detect_domain(out: dict, user_description: str = "") -> tuple[str, dict[str, int]]:
    t = text_blob(out, user_description)
    scores = {
        "technology_ram": 0,
        "technology_gpu": 0,
        "technology_generic": 0,
        "home": 0,
        "garden": 0,
        "outdoor": 0,
        "tools": 0,
        "vehicle": 0,
        "clothing": 0,
        "collectibles": 0,
        "generic": 1,
    }

    def hit(domain: str, terms: list[str], weight: int = 1):
        scores[domain] += sum(weight for term in terms if term in t)

    hit("technology_ram", ["ram", "memoria", "ddr", "sodimm", "ecc", "rdimm", "udimm"], 2)
    hit("technology_gpu", ["scheda video", "gpu", "vram", "rtx", "radeon", "quadro", "geforce"], 2)
    hit("technology_generic", ["ssd", "nvme", "cpu", "processore", "scheda madre", "monitor", "notebook", "tablet", "iphone", "android"], 2)
    hit("home", ["sedia", "sedie", "tavolo", "divano", "mobile", "armadio", "lampada", "letto", "materasso", "cucina", "tapparella", "tapparelle", "serranda", "serrande", "avvolgibile", "avvolgibili", "persiana", "persiane", "infissi", "zanzariera"], 2)
    hit("garden", ["giardino", "tosaerba", "decespugliatore", "motosega", "tagliasiepi", "soffiatore", "irrigazione", "vaso"], 2)
    hit("outdoor", ["campeggio", "camping", "trekking", "tenda", "zaino", "sacco a pelo", "scarponi", "survival", "bushcraft"], 2)
    hit("tools", ["trapano", "avvitatore", "smerigliatrice", "compressore", "utensile", "bosch", "makita", "dewalt", "beta"], 2)
    hit("vehicle", ["auto", "moto", "cerchi", "pneumatici", "gomme", "ruote", "ricambi auto", "scooter"], 2)
    hit("clothing", ["taglia", "scarpe", "giacca", "pantaloni", "vestito", "felpa", "zaino"], 1)
    hit("collectibles", ["collezione", "figurina", "lego", "fumetto", "vinile", "retrogame", "pokemon", "carta"], 2)

    # Tie breakers.
    if scores["technology_ram"] >= 4:
        scores["technology_generic"] += 1
    if scores["technology_gpu"] >= 4:
        scores["technology_generic"] += 1

    domain = max(scores, key=scores.get)
    return domain, scores


def ensure_platforms_vision(out: dict) -> None:
    out["platforms"] = DEFAULT_PLATFORMS[:]
    out["vision_enabled"] = True
    out["context_check_enabled"] = True


def apply_technology_common(out: dict, user_description: str, warnings: list[str]) -> None:
    t = text_blob(out, user_description)

    add_terms(out, "exclude_words", ["guasto", "difettoso", "non funzionante", "per parti", "solo scatola"], 40)
    add_terms(out, "reject_patterns", ["guasto", "difettoso", "non funzionante", "per parti", "solo scatola"], 40)
    add_terms(out, "distractor_words", ["bundle", "pc completo", "computer intero", "preassemblato", "venduto con altri componenti"], 40)

    if any(x in t for x in ["bundle", "pc completo", "computer intero", "separatamente", "smembra", "vende a pezzi"]):
        moved = []
        for key in ["exclude_words", "reject_patterns"]:
            moved += remove_terms(out, key, {"bundle", "pc completo", "computer completo", "computer intero", "preassemblato", "preassemblati"})
        if moved:
            add_terms(out, "distractor_words", moved, 40)


def apply_ram_profile(out: dict, user_description: str, warnings: list[str]) -> None:
    apply_technology_common(out, user_description, warnings)
    add_terms(out, "exclude_words", ["sodimm", "so-dimm", "ecc", "rdimm", "registered", "server", "laptop", "notebook", "portatile"], 40)
    add_terms(out, "reject_patterns", ["sodimm", "so-dimm", "ecc", "rdimm", "registered", "server", "laptop", "notebook", "portatile"], 40)

    t = text_blob(out, user_description)
    if "ddr4" in t:
        add_terms(out, "exclude_words", ["ddr2", "ddr3", "ddr5"], 40)
        add_terms(out, "reject_patterns", ["ddr2", "ddr3", "ddr5"], 40)

    # If 16/32GB are target capacities, 4/8GB kits are true rejects, not distractors.
    caps = set()
    for group in as_list(out.get("required_groups")):
        if isinstance(group, list):
            for x in group:
                m = re.fullmatch(r"\s*(\d+)\s*gb\s*", str(x).lower())
                if m:
                    caps.add(int(m.group(1)))
    if not caps:
        for m in re.finditer(r"(\d+)\s*gb", t):
            try:
                caps.add(int(m.group(1)))
            except Exception:
                pass

    if caps and min(caps) >= 16:
        low_bad = []
        for v in [4, 8]:
            if v < min(caps):
                low_bad += [f"{v}gb", f"{v} gb", f"kit da {v}gb", f"kit da {v} gb", f"ddr4 {v}gb", f"{v}gb ddr4"]
        add_terms(out, "exclude_words", low_bad, 40)
        add_terms(out, "reject_patterns", low_bad, 40)
        bad = {clean(x) for x in low_bad}
        for key in ["distractor_words", "negative_keywords"]:
            remove_terms(out, key, bad)

    warnings.append("profilo euristico: tecnologia/RAM")


def apply_gpu_profile(out: dict, user_description: str, warnings: list[str]) -> None:
    apply_technology_common(out, user_description, warnings)
    t = text_blob(out, user_description)
    m = re.search(r"(?:minimo|almeno|>=|non meno di)\s*(\d+)\s*gb", t)
    min_vram = int(m.group(1)) if m else (24 if "24gb" in t.replace(" ", "") else None)

    if min_vram:
        if min_vram == 24:
            preferred = ["gpu 24gb", "scheda video 24gb", "vram 24gb", "24gb vram", "rtx 3090", "rtx 4090", "quadro 24gb", "rtx a5000", "rtx a6000"]
        else:
            preferred = [f"gpu {min_vram}gb", f"scheda video {min_vram}gb", f"vram {min_vram}gb", f"{min_vram}gb vram"]

        old_kw = []
        for kw in as_list(out.get("search_keywords")):
            s = clean(kw)
            if re.search(r"\b\d{3,5}\b", s):
                continue
            if any(x in s for x in ["controlla", "budget", "minimo"]):
                continue
            old_kw.append(s)
        out["search_keywords"] = dedup(preferred + old_kw, 16)

        sizes = [min_vram] + [s for s in [32, 48, 64, 80] if s > min_vram]
        size_group = []
        for s in sizes:
            size_group += [f"{s}gb", f"{s} gb"]
        out["required_groups"] = [["scheda video", "gpu", "vga"], ["vram"], dedup(size_group, 16)]

    # PC completi are AI distractors if user wants separate sale.
    if any(x in t for x in ["pc complet", "computer", "separatamente", "smembra", "vendere separatamente"]):
        moved = []
        for key in ["exclude_words", "reject_patterns"]:
            moved += remove_terms(out, key, {"kit", "bundle", "preassemblato", "pc completo", "computer completo", "computer intero", "computer", "pc"})
        add_terms(out, "distractor_words", moved + ["pc completo", "computer completo", "preassemblato", "vendita separata", "non vendibile separatamente"], 40)

    warnings.append("profilo euristico: tecnologia/GPU")


def apply_home_profile(out: dict, user_description: str, warnings: list[str]) -> None:
    add_terms(out, "distractor_words", ["lotto", "set", "ritiro", "misure da verificare", "colore diverso", "solo struttura"], 40)
    add_terms(out, "exclude_words", ["rotto", "danneggiato", "da riparare", "solo ricambio"], 40)
    add_terms(out, "reject_patterns", ["rotto", "danneggiato", "da riparare", "solo ricambio"], 40)
    warnings.append("profilo euristico: casa")


def apply_garden_profile(out: dict, user_description: str, warnings: list[str]) -> None:
    add_terms(out, "distractor_words", ["solo batteria", "solo caricatore", "solo lama", "ricambio", "accessorio", "non funzionante"], 40)
    add_terms(out, "exclude_words", ["giocattolo", "miniatura", "non funzionante", "guasto", "da riparare"], 40)
    add_terms(out, "reject_patterns", ["giocattolo", "miniatura", "non funzionante", "guasto", "da riparare"], 40)
    warnings.append("profilo euristico: giardino")


def apply_outdoor_profile(out: dict, user_description: str, warnings: list[str]) -> None:
    add_terms(out, "distractor_words", ["bambino", "junior", "giocattolo", "miniatura", "accessorio", "custodia", "ricambio"], 40)
    add_terms(out, "exclude_words", ["rotto", "strappato", "non funzionante", "solo custodia"], 40)
    add_terms(out, "reject_patterns", ["rotto", "strappato", "non funzionante", "solo custodia"], 40)
    warnings.append("profilo euristico: outdoor/campeggio")


def threshold_unit_variants(value: int, unit: str) -> list[int]:
    unit = clean(unit)
    tables = {
        "v": [10, 12, 14, 14.4, 18, 20, 24, 36, 40, 48, 54, 60],
        "volt": [10, 12, 14, 14.4, 18, 20, 24, 36, 40, 48, 54, 60],
        "ah": [1, 1.5, 2, 3, 4, 5, 6, 8, 9, 10, 12],
        "mah": [1000, 1500, 2000, 3000, 4000, 5000, 6000, 8000, 10000],
        "w": [300, 400, 500, 600, 700, 800, 1000, 1200, 1500, 2000],
        "watt": [300, 400, 500, 600, 700, 800, 1000, 1200, 1500, 2000],
        "hz": [60, 75, 100, 120, 144, 165, 175, 180, 200, 240, 280, 300, 360, 500],
        "kg": [1, 2, 3, 5, 10, 15, 20, 25, 30, 40, 50],
        "l": [10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 100],
        "litri": [10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 100],
        "mm": [6, 8, 10, 12, 13, 16, 18, 20, 22, 25, 30, 32, 40],
        "cm": [10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 120, 140, 160, 180, 200],
        "gb": [4, 8, 12, 16, 24, 32, 48, 64, 80, 96, 128, 256],
        "tb": [1, 2, 4, 8, 12, 16, 20, 24],
    }
    seq = tables.get(unit, [])
    out = []
    for x in seq:
        try:
            if float(x) >= float(value):
                out.append(int(x) if float(x).is_integer() else x)
        except Exception:
            pass
    if value not in out:
        out.insert(0, value)
    return out[:8]


def extract_min_thresholds(user_description: str, out: dict | None = None) -> list[dict]:
    text = clean((user_description or "") + " " + str((out or {}).get("item_description", "")))
    patterns = [
        r"(?:almeno|minimo|>=|non meno di|da almeno)\s*(\d+(?:[.,]\d+)?)\s*(v|volt|ah|mah|w|watt|hz|kg|l|litri|mm|cm|gb|tb)\b",
        r"(\d+(?:[.,]\d+)?)\s*(v|volt|ah|mah|w|watt|hz|kg|l|litri|mm|cm|gb|tb)\s*(?:o più|in su|minimo|almeno)\b",
    ]
    found = []
    seen = set()
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            raw_value = m.group(1).replace(",", ".")
            unit = clean(m.group(2))
            try:
                value_f = float(raw_value)
            except Exception:
                continue
            value = int(value_f) if value_f.is_integer() else value_f
            key = (value, unit)
            if key in seen:
                continue
            seen.add(key)
            found.append({"value": value, "unit": unit, "variants": threshold_unit_variants(value, unit)})
    return found


def infer_main_product_terms(user_description: str, out: dict) -> list[str]:
    text = clean(user_description + " " + str(out.get("item_description", "")))
    candidates = []

    product_terms = [
        "trapano", "avvitatore", "trapano avvitatore", "smerigliatrice", "seghetto", "tassellatore",
        "decespugliatore", "motosega", "tosaerba", "soffiatore",
        "monitor", "scheda video", "gpu", "ssd", "batteria", "zaino", "tenda",
    ]
    for term in product_terms:
        if term in text:
            candidates.append(term)

    # Prefer existing product-ish required group if present.
    for group in as_list(out.get("required_groups")):
        if isinstance(group, list) and group:
            joined = " ".join(clean(x) for x in group)
            if not any(re.search(rf"\b\d+\s*{u}\b", joined) for u in ["v", "volt", "ah", "mah", "w", "hz", "gb", "tb", "mm", "cm"]):
                for x in group:
                    sx = clean(x)
                    if sx and len(sx) > 2:
                        candidates.append(sx)

    return dedup(candidates, 6)


def apply_generic_threshold_profile(out: dict, user_description: str, warnings: list[str]) -> None:
    thresholds = extract_min_thresholds(user_description, out)
    if not thresholds:
        return

    product_terms = infer_main_product_terms(user_description, out)
    changed = False

    required_groups = as_list(out.get("required_groups"))
    if not required_groups and product_terms:
        required_groups = [product_terms[:4]]

    search = as_list(out.get("search_keywords"))
    for th in thresholds:
        unit = th["unit"]
        variants = th["variants"]
        group = []
        for v in variants:
            label = str(v).replace(".0", "")
            group.extend([f"{label}{unit}", f"{label} {unit}"])
            # normalized aliases
            if unit == "volt":
                group.extend([f"{label}v", f"{label} v"])
            if unit == "v":
                group.extend([f"{label}volt", f"{label} volt"])

        group = dedup(group, 16)
        if group and group not in required_groups:
            required_groups.append(group)
            changed = True

        # Add short marketplace queries: product + threshold variants.
        base_terms = product_terms[:2] or []
        for base in base_terms:
            for v in variants[:5]:
                label = str(v).replace(".0", "")
                short_unit = "v" if unit == "volt" else unit
                search.append(f"{base} {label}{short_unit}")

    if search:
        out["search_keywords"] = dedup(search, 18)

    if required_groups:
        out["required_groups"] = required_groups

    if changed:
        pretty = ", ".join(f"{th['value']}{th['unit']}+" for th in thresholds)
        warnings.append(f"profilo soglie numeriche: {pretty}")


def apply_tools_profile(out: dict, user_description: str, warnings: list[str]) -> None:
    add_terms(out, "distractor_words", ["solo batteria", "solo caricatore", "valigetta vuota", "accessorio", "ricambio"], 40)
    add_terms(out, "exclude_words", ["guasto", "non funzionante", "da riparare", "per ricambi"], 40)
    add_terms(out, "reject_patterns", ["guasto", "non funzionante", "da riparare", "per ricambi"], 40)
    warnings.append("profilo euristico: utensili/fai-da-te")


def apply_vehicle_profile(out: dict, user_description: str, warnings: list[str]) -> None:
    add_terms(out, "distractor_words", ["ricambio compatibile", "solo cerchio", "solo gomma", "set incompleto", "misura da verificare"], 40)
    add_terms(out, "exclude_words", ["incidentato", "rotto", "non funzionante"], 40)
    add_terms(out, "reject_patterns", ["incidentato", "rotto", "non funzionante"], 40)
    warnings.append("profilo euristico: auto/moto")


def apply_domain_profile(out: dict, user_description: str = "") -> tuple[dict, list[str]]:
    warnings: list[str] = []
    ensure_platforms_vision(out)
    domain, scores = detect_domain(out, user_description)

    if domain == "technology_ram":
        apply_ram_profile(out, user_description, warnings)
    elif domain == "technology_gpu":
        apply_gpu_profile(out, user_description, warnings)
    elif domain == "technology_generic":
        apply_technology_common(out, user_description, warnings)
        warnings.append("profilo euristico: tecnologia/generico")
    elif domain == "home":
        apply_home_profile(out, user_description, warnings)
    elif domain == "garden":
        apply_garden_profile(out, user_description, warnings)
    elif domain == "outdoor":
        apply_outdoor_profile(out, user_description, warnings)
    elif domain == "tools":
        apply_tools_profile(out, user_description, warnings)
    elif domain == "vehicle":
        apply_vehicle_profile(out, user_description, warnings)
    else:
        warnings.append("profilo euristico: generico")

    apply_generic_threshold_profile(out, user_description, warnings)

    out["domain_profile"] = domain
    return out, warnings
