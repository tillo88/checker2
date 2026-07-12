from __future__ import annotations
import json, re
from pathlib import Path
from .models import SpyConfig
from spyengine.wizard.domain_profiles import apply_domain_profile
from spyengine.utils.text import normalize_text


def normalize_config_name(path: str, data: dict) -> str:
    name = str(data.get("config_name") or Path(path).stem.replace("spy_config_", ""))
    name = re.sub(r"[^a-z0-9_]+", "_", name.lower().strip())
    return name.strip("_") or "spy"


def normalize_budget(raw_budget) -> dict[str, float]:
    if isinstance(raw_budget, (int, float)):
        return {"standard": float(raw_budget)}
    if isinstance(raw_budget, dict):
        configs = raw_budget.get("configurations")
        if isinstance(configs, dict) and configs:
            out = {}
            for k, v in configs.items():
                try:
                    out[str(k)] = float(v)
                except Exception:
                    pass
            if out:
                return out
        try:
            return {"standard": float(raw_budget.get("default", 100.0))}
        except Exception:
            pass
    return {"standard": 100.0}


def normalize_required_groups(raw_groups) -> list[list[str]]:
    """
    Groups of alternatives. Every group must match at least one term.

    Example:
    [
      ["ddr4"],
      ["ram", "memoria"],
      ["32gb", "32 gb", "16gb", "16 gb"]
    ]
    """
    if not isinstance(raw_groups, list):
        return []

    out: list[list[str]] = []
    for group in raw_groups:
        if isinstance(group, str):
            group = [group]
        if not isinstance(group, list):
            continue

        cleaned = []
        seen = set()
        for value in group:
            s = str(value).strip().lower()
            if not s or s in seen:
                continue
            seen.add(s)
            cleaned.append(s)

        if cleaned:
            out.append(cleaned)

    return out


def normalize_unit_budget_rules(raw_rules) -> list[dict]:
    """
    Generic per-unit budget rules.

    Example:
    {
      "name": "32gb_per_stick",
      "match": ["32gb", "32 gb"],
      "max_price_per_unit": 143,
      "unit": "stick"
    }

    Works for RAM sticks, chairs, tyres, plates, bulk CPUs/GPUs, etc.
    """
    if not isinstance(raw_rules, list):
        return []

    out: list[dict] = []
    for idx, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            continue

        match = raw.get("match", raw.get("matches", raw.get("terms", [])))
        if isinstance(match, str):
            match = [match]
        if not isinstance(match, list):
            continue
        match = [str(x).strip() for x in match if str(x).strip()]
        if not match:
            continue

        try:
            max_price = float(raw.get("max_price_per_unit", raw.get("max_unit_price", raw.get("budget_per_unit"))))
        except Exception:
            continue
        if max_price <= 0:
            continue

        unit_aliases = raw.get("unit_aliases", raw.get("aliases", []))
        if isinstance(unit_aliases, str):
            unit_aliases = [unit_aliases]
        if not isinstance(unit_aliases, list):
            unit_aliases = []

        out.append(
            {
                "name": str(raw.get("name") or raw.get("config") or f"unit_rule_{idx + 1}"),
                "match": match,
                "max_price_per_unit": max_price,
                "unit": str(raw.get("unit") or "unit"),
                "unit_aliases": [str(x).strip() for x in unit_aliases if str(x).strip()],
            }
        )

    return out


def _clean_lower(value: str) -> str:
    return str(value or "").strip().lower()


def repair_required_groups_for_data(groups: list[list[str]], data: dict) -> list[list[str]]:
    joined = " ".join(
        [
            _clean_lower(data.get("item_description", "")),
            " ".join(_clean_lower(x) for x in data.get("search_keywords", []) if isinstance(x, str)),
            " ".join(_clean_lower(x) for x in data.get("required_words", []) if isinstance(x, str)),
        ]
    )
    compact = joined.replace(" ", "")

    if "ddr4" in compact and ("ram" in joined or "memoria" in joined):
        size_group = []
        if "32gb" in compact:
            size_group.extend(["32gb", "32 gb"])
        if "16gb" in compact:
            size_group.extend(["16gb", "16 gb"])
        if not size_group:
            size_group = ["32gb", "32 gb", "16gb", "16 gb"]

        # Dedup while preserving order.
        seen = set()
        size_group = [x for x in size_group if not (x in seen or seen.add(x))]
        return [["ddr4"], ["ram", "memoria"], size_group]

    if groups:
        capacity_terms = {"32gb", "32 gb", "16gb", "16 gb", "64gb", "64 gb", "128gb", "128 gb"}
        unit_terms = {"banco", "banchi", "modulo", "moduli", "singolo", "singolo modulo", "kit", "multipli"}
        capacity = []
        out = []
        for group in groups:
            gset = set(group)
            if gset and gset.issubset(capacity_terms):
                capacity.extend(group)
            elif gset and gset.issubset(unit_terms):
                continue
            else:
                out.append(group)
        if capacity:
            seen = set()
            out.append([x for x in capacity if not (x in seen or seen.add(x))])
        return out

    return groups


def repair_hard_rejects_for_data(values: list[str], data: dict) -> list[str]:
    joined = _clean_lower(data.get("item_description", "")) + " " + _clean_lower(data.get("system_prompt", ""))
    wants_bundle_review = any(x in joined for x in ["bundle", "pc inter", "computer inter", "smembra", "vendita a pezzi", "vende a pezzi"])
    wants_kit_or_multi = any(x in joined for x in ["kit", "multipli", "combinazioni", "2x", "3x", "4x", "nx"])
    false_hard = {"kit gaming", "offerta speciale", "garanzia estesa", "spedizione gratuita"}
    if wants_bundle_review or wants_kit_or_multi:
        false_hard.update({
            "kit", "kit ram", "kit completo", "kit di ram multipla",
            "bundle", "bundle pc", "bundle computer", "bundle computer completo",
            "pc completo", "computer completo", "computer intero",
            "preassemblato", "preassemblati", "computer nuovo",
            "pacchetto", "lotto", "pezzi",
        })

    out = []
    seen = set()
    for value in values or []:
        s = _clean_lower(value)
        if not s or s in false_hard:
            continue
        if any(ord(ch) > 127 and ch not in "àèéìòùç" for ch in s):
            continue
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def add_incompatibilities_for_data(values: list[str], data: dict) -> list[str]:
    out = repair_hard_rejects_for_data(values, data)
    joined = _clean_lower(data.get("item_description", ""))
    if "ddr4" in joined:
        for term in ["ddr2", "ddr3", "ddr5"]:
            if term not in out:
                out.append(term)
    return out


def _gb_value_from_term(term: str) -> int | None:
    s = re.sub(r"\\s+", "", str(term).lower())
    m = re.fullmatch(r"(\\d+)gb", s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _dedup_str(values, limit=40):
    out = []
    seen = set()
    for value in values or []:
        s = str(value).strip().lower()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def repair_soft_hard_conflicts_for_data(data: dict) -> dict:
    hard_terms = set()
    for key in ["exclude_words", "reject_patterns"]:
        hard_terms.update(str(x).strip().lower() for x in data.get(key, []) if str(x).strip())

    for key in ["distractor_words", "negative_keywords"]:
        data[key] = [x for x in data.get(key, []) if str(x).strip().lower() not in hard_terms]

    joined = (str(data.get("item_description", "")) + " " + str(data.get("system_prompt", ""))).lower()
    wants_bundle_review = any(x in joined for x in ["bundle", "pc inter", "computer inter", "smembra", "vendita a pezzi", "vende a pezzi", "separatamente"])
    wants_kit_or_multi = any(x in joined for x in ["kit", "multipli", "combinazioni", "2x", "3x", "4x", "nx"])
    if wants_bundle_review or wants_kit_or_multi:
        bundle_terms = {"kit", "kit ram", "kit completo", "bundle", "bundle pc", "bundle computer", "pc completo", "computer completo", "computer intero", "preassemblato"}
        moved = []
        for key in ["exclude_words", "reject_patterns"]:
            kept = []
            for v in data.get(key, []):
                s = str(v).strip().lower()
                if s in bundle_terms:
                    moved.append(s)
                else:
                    kept.append(v)
            data[key] = _dedup_str(kept)
        data["distractor_words"] = _dedup_str(list(data.get("distractor_words", [])) + moved)

    allowed = set()
    for group in data.get("required_groups", []) or []:
        if isinstance(group, list):
            for x in group:
                v = _gb_value_from_term(x)
                if v:
                    allowed.add(v)
    if allowed and min(allowed) >= 16:
        low_bad = []
        for v in [4, 8]:
            if v < min(allowed):
                low_bad.extend([f"{v}gb", f"{v} gb", f"kit da {v}gb", f"kit da {v} gb", f"{v}gb ddr4", f"ddr4 {v}gb"])
        for key in ["exclude_words", "reject_patterns"]:
            data[key] = _dedup_str(list(data.get(key, [])) + low_bad)
        badset = set(low_bad)
        for key in ["distractor_words", "negative_keywords"]:
            data[key] = _dedup_str([x for x in data.get(key, []) if str(x).strip().lower() not in badset])

    return data


def repair_gpu_threshold_for_data(data: dict) -> dict:
    joined = (str(data.get("item_description", "")) + " " + str(data.get("system_prompt", ""))).lower()
    if not (("scheda video" in joined or "gpu" in joined or "vga" in joined) and "vram" in joined):
        return data

    m = re.search(r"(?:minimo|almeno|>=|non meno di)\\s*(\\d+)\\s*gb", joined)
    min_vram = int(m.group(1)) if m else (24 if "24gb" in joined.replace(" ", "") else None)
    if not min_vram:
        return data

    if min_vram == 24:
        preferred = ["gpu 24gb", "scheda video 24gb", "vram 24gb", "24gb vram", "rtx 3090", "rtx 4090", "quadro 24gb", "rtx a5000", "rtx a6000"]
    else:
        preferred = [f"gpu {min_vram}gb", f"scheda video {min_vram}gb", f"vram {min_vram}gb", f"{min_vram}gb vram"]

    old_kw = []
    for kw in data.get("search_keywords", []) or []:
        s = str(kw).strip().lower()
        if re.search(r"\\b\\d{3,5}\\b", s):
            continue
        if any(x in s for x in ["controlla", "budget", "minimo"]):
            continue
        old_kw.append(s)
    data["search_keywords"] = _dedup_str(preferred + old_kw, 16)

    sizes = [min_vram] + [s for s in [32, 48, 64, 80] if s > min_vram]
    size_group = []
    for s in sizes:
        size_group.extend([f"{s}gb", f"{s} gb"])
    data["required_groups"] = [["scheda video", "gpu", "vga"], ["vram"], _dedup_str(size_group, 16)]

    if any(x in joined for x in ["pc complet", "computer", "separatamente", "smembra"]):
        remove = {"kit", "bundle", "preassemblato", "pc completo", "computer completo", "computer intero"}
        for key in ["exclude_words", "reject_patterns"]:
            data[key] = _dedup_str([x for x in data.get(key, []) if str(x).strip().lower() not in remove])
        data["distractor_words"] = _dedup_str(list(data.get("distractor_words", [])) + ["pc completo", "computer completo", "preassemblato", "vendita separata", "non vendibile separatamente"])

    return data


def fix_mojibake_text(value: str) -> str:
    s = str(value)
    markers = ("â", "Ã", "Â", "ð", "ç¬", "è®", "æ")
    if not any(m in s for m in markers):
        return s
    try:
        repaired = s.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
        old_score = sum(s.count(m) for m in markers)
        new_score = sum(repaired.count(m) for m in markers)
        if repaired and new_score <= old_score:
            return repaired
    except Exception:
        pass
    return s


def fix_mojibake_in_obj(value):
    if isinstance(value, str):
        return fix_mojibake_text(value)
    if isinstance(value, list):
        return [fix_mojibake_in_obj(x) for x in value]
    if isinstance(value, dict):
        return {fix_mojibake_text(k): fix_mojibake_in_obj(v) for k, v in value.items()}
    return value


def collect_strings_from_obj(value) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, list):
        for x in value:
            out.extend(collect_strings_from_obj(x))
    elif isinstance(value, dict):
        for k, v in value.items():
            out.append(str(k))
            out.extend(collect_strings_from_obj(v))
    return out


def extract_unit_prices_for_data(data: dict) -> dict[str, float]:
    text = " ".join(collect_strings_from_obj({
        "item_description": data.get("item_description", ""),
        "system_prompt": data.get("system_prompt", ""),
    }))
    text = fix_mojibake_text(text)
    low = text.lower()
    low = re.sub(r"\s+", " ", low).strip()
    compact = low.replace(" ", "")

    variants = []
    for variant in ["128gb", "64gb", "48gb", "32gb", "24gb", "16gb", "8gb", "4gb"]:
        if variant in compact:
            variants.append(variant)

    prices: dict[str, float] = {}
    has_tolerance = "+10" in low or "10%" in low or "10 per cento" in low

    for variant in variants:
        num = variant.replace("gb", "")
        forms = [variant, variant.replace("gb", " gb")]
        candidates = []

        for form in forms:
            patterns = [
                rf"(\d+(?:[.,]\d+)?)\s*(?:€|eur|euro)?\s*(?:per|/)?\s*(?:ogni\s+)?(?:banco|banchi|modulo|moduli|stick|unit[aà]|pezzo|pezzi)?(?:\s+di\s+memoria|\s+da|\s+di)?\s*{re.escape(form)}",
                rf"{re.escape(form)}(?:\s+\w+){{0,10}}\s+(\d+(?:[.,]\d+)?)\s*(?:€|eur|euro)",
                rf"(?:prezzo\s+massimo|max|massimo)(?:\s+\w+){{0,12}}\s+{re.escape(form)}(?:\s+\w+){{0,8}}\s+(\d+(?:[.,]\d+)?)\s*(?:€|eur|euro)",
            ]
            for pattern in patterns:
                for m in re.finditer(pattern, low):
                    try:
                        val = float(m.group(1).replace(",", "."))
                    except Exception:
                        continue
                    if val > 0 and abs(val - float(num)) > 0.01:
                        candidates.append(val)

        if candidates:
            val = max(candidates)
            if has_tolerance:
                if abs(val - 130.0) < 0.01:
                    val = 143.0
                elif abs(val - 60.0) < 0.01:
                    val = 66.0
            prices[variant] = float(val)

    return prices


def is_gpu_config_data(data: dict) -> bool:
    text = normalize_text(" ".join(collect_strings_from_obj({
        "domain_profile": data.get("domain_profile", ""),
        "name": data.get("name", ""),
        "item_description": data.get("item_description", ""),
        "search_keywords": data.get("search_keywords", []),
        "required_groups": data.get("required_groups", []),
        "system_prompt": data.get("system_prompt", ""),
    })))
    return (
        data.get("domain_profile") == "technology_gpu"
        or "scheda video" in text
        or re.search(r"(?<![a-z0-9])gpu(?![a-z0-9])", text) is not None
        or "vram" in text
    )


def repair_gpu_budget_shape_for_data(data: dict, rules: list[dict]) -> tuple[dict, list[dict], dict]:
    """
    GPU/VRAM budgets are total-card budgets. Capacity values like 24GB VRAM
    must not become unit_budget_rules/config_patterns.
    """
    if not is_gpu_config_data(data):
        return normalize_budget(data.get("budget", {})), rules, data.get("config_patterns", {})

    budget = data.get("budget") if isinstance(data.get("budget"), dict) else {}
    total = None

    try:
        if budget.get("default") is not None:
            total = float(budget.get("default"))
    except Exception:
        total = None

    if not total or total <= 0:
        vals = []
        for v in (budget.get("configurations") or {}).values():
            try:
                fv = float(v)
                if fv > 0:
                    vals.append(fv)
            except Exception:
                pass
        if vals:
            total = max(vals)

    if not total or total <= 0:
        text = normalize_text(str(data.get("item_description", "")) + " " + str(data.get("system_prompt", "")))
        m = re.search(r"(?:budget|prezzo massimo|max|massimo)\D{0,20}(\d+(?:[.,]\d+)?)\s*(?:€|eur|euro)?", text)
        if m:
            try:
                total = float(m.group(1).replace(",", "."))
            except Exception:
                total = None

    if not total or total <= 0:
        total = 0.0

    fixed_budget = {
        "default": float(total),
        "configurations": {"standard": float(total)},
    }
    return fixed_budget, [], {"standard": []}




def repair_suspicious_unit_budget_rules_for_data(data: dict, rules: list[dict]) -> list[dict]:
    extracted = extract_unit_prices_for_data(data)
    if not extracted:
        return rules

    repaired = []
    changed = False
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        variant = _variant_from_rule(rule)
        try:
            old_price = float(rule.get("max_price_per_unit", 0))
        except Exception:
            old_price = 0.0
        new_rule = dict(rule)
        if variant and variant in extracted:
            target_price = float(extracted[variant])
            cap_value = float(variant.replace("gb", ""))
            suspicious = old_price <= cap_value + 0.01 or old_price <= 0
            if suspicious or target_price >= old_price * 1.5:
                new_rule["max_price_per_unit"] = target_price
                changed = True
        repaired.append(new_rule)

    if not repaired:
        for variant, price in extracted.items():
            repaired.append({
                "name": f"{variant.upper()} banco",
                "match": [variant, variant.replace("gb", " gb")],
                "max_price_per_unit": price,
                "unit": "banco",
                "unit_aliases": ["banco", "banchi", "modulo", "moduli", "stick"],
            })
            changed = True

    return normalize_unit_budget_rules(repaired) if changed else rules


def infer_unit_budget_rules_for_data(data: dict, existing_rules: list[dict]) -> list[dict]:
    if existing_rules:
        return existing_rules

    text = " ".join(
        collect_strings_from_obj(
            {
                "item_description": data.get("item_description", ""),
                "budget": data.get("budget", {}),
                "system_prompt": data.get("system_prompt", ""),
                "budget_rules": data.get("budget_rules", []),
            }
        )
    )
    text = fix_mojibake_text(text)
    low = text.lower()
    normalized = re.sub(r"\s+", " ", low)
    compact = normalized.replace(" ", "")

    if not any(unit_word in normalized for unit_word in ["per banco", "per modulo", "per stick", "per unit", "per pezzo", "per ogni"]):
        return existing_rules

    variants = [v for v in ["128gb", "64gb", "32gb", "16gb", "8gb", "4gb"] if v in compact]
    if not variants:
        return existing_rules

    price_matches = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(?:€|eur|euro)?", normalized):
        try:
            value = float(m.group(1).replace(",", "."))
        except Exception:
            continue
        if 5 <= value <= 10000:
            price_matches.append((m.start(), value))

    has_tolerance = "+10" in normalized or "10%" in normalized or "10 per cento" in normalized

    def bump(price: float) -> float:
        if has_tolerance and abs(price - 130.0) < 0.01:
            return 143.0
        if has_tolerance and abs(price - 60.0) < 0.01:
            return 66.0
        return float(price)

    rules = []
    seen = set()
    for variant in variants:
        forms = [variant, variant.replace("gb", " gb")]
        positions = [m.start() for form in forms for m in re.finditer(re.escape(form), normalized)]
        candidates = []
        for pos in positions:
            for ppos, price in price_matches:
                dist = abs(ppos - pos)
                if dist <= 110:
                    candidates.append((dist, price))
        if not candidates:
            continue
        candidates.sort(key=lambda x: x[0])
        price = bump(candidates[0][1])
        if variant in seen or price <= 0:
            continue
        seen.add(variant)
        rules.append(
            {
                "name": f"{variant.upper()} banco",
                "match": [variant, variant.replace("gb", " gb")],
                "max_price_per_unit": price,
                "unit": "banco" if ("ram" in normalized or "memoria" in normalized) else "unità",
                "unit_aliases": ["banco", "banchi", "modulo", "moduli", "stick"] if ("ram" in normalized or "memoria" in normalized) else ["unità", "pezzo", "pezzi"],
            }
        )

    return normalize_unit_budget_rules(rules)


def _variant_from_rule(rule: dict) -> str | None:
    text = " ".join(str(x).lower().replace(" ", "") for x in rule.get("match", []) if isinstance(x, str))
    text += " " + str(rule.get("name", "")).lower().replace(" ", "")
    for variant in ["32gb", "16gb", "64gb", "8gb", "4gb"]:
        if variant in text:
            return variant
    return None


def repair_budget_from_unit_rules_for_data(raw_budget, unit_rules) -> dict[str, float]:
    # load_config stores budget as flat dict[str,float], preserving previous normalize_budget behavior.
    normalized = normalize_budget(raw_budget)
    if not isinstance(unit_rules, list) or not unit_rules:
        return normalized

    out = {}
    values = []
    for rule in unit_rules:
        if not isinstance(rule, dict):
            continue
        try:
            price = float(rule.get("max_price_per_unit", 0))
        except Exception:
            continue
        if price <= 0:
            continue
        values.append(price)
        variant = _variant_from_rule(rule)
        if variant:
            out[variant] = price

    if not values:
        return normalized

    for k, v in normalized.items():
        if v > 0 and str(k).lower() not in {"standard", "max", "max_price"}:
            out[str(k)] = float(v)

    if "standard" not in out:
        out["standard"] = max(values)

    return out or {"standard": max(values)}


def load_config(path: str | Path) -> SpyConfig:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data = fix_mojibake_in_obj(data)
    data = repair_gpu_threshold_for_data(data)
    data = repair_soft_hard_conflicts_for_data(data)
    data, _domain_warnings = apply_domain_profile(data, user_description=str(data.get("item_description", "")))
    data = repair_soft_hard_conflicts_for_data(data)

    exclude_words_repaired = add_incompatibilities_for_data(list(data.get("exclude_words", [])), data)
    reject_patterns_repaired = add_incompatibilities_for_data(list(data.get("reject_patterns", [])), data)
    required_groups_repaired = repair_required_groups_for_data(
        normalize_required_groups(data.get("required_groups", [])),
        data,
    )
    unit_budget_rules_repaired = normalize_unit_budget_rules(data.get("unit_budget_rules", []))
    unit_budget_rules_repaired = infer_unit_budget_rules_for_data(data, unit_budget_rules_repaired)
    unit_budget_rules_repaired = repair_suspicious_unit_budget_rules_for_data(data, unit_budget_rules_repaired)
    budget_repaired = repair_budget_from_unit_rules_for_data(data.get("budget", {}), unit_budget_rules_repaired)
    budget_repaired, unit_budget_rules_repaired, config_patterns_repaired = repair_gpu_budget_shape_for_data(data, unit_budget_rules_repaired)

    return SpyConfig(
        name=normalize_config_name(str(path), data),
        item_description=data.get("item_description", "oggetto"),
        search_keywords=list(data.get("search_keywords", data.get("keywords", []))),
        exclude_words=exclude_words_repaired,
        required_words=list(data.get("required_words", [])),
        required_groups=required_groups_repaired,
        distractor_words=list(data.get("distractor_words", [])),
        budget=budget_repaired,
        unit_budget_rules=unit_budget_rules_repaired,
        config_patterns=config_patterns_repaired if isinstance(config_patterns_repaired, dict) else dict(data.get("config_patterns", {})),
        reject_patterns=reject_patterns_repaired,
        premium_brands=list(data.get("premium_brands", [])),
        positive_keywords={str(k): int(v) for k, v in dict(data.get("positive_keywords", {})).items()},
        negative_keywords=list(data.get("negative_keywords", [])),
        platforms=list(data.get("platforms", ["VINTED", "SUBITO", "EBAY", "WALLAPOP"])),
        vision_enabled=bool(data.get("vision_enabled", True)),
        context_check_enabled=bool(data.get("context_check_enabled", True)),
        interval_seconds=int(data.get("interval_seconds", 300)),
        max_history=int(data.get("max_history", 200)),
        ebay_app_id_env=data.get("ebay_app_id_env", "EBAY_APP_ID"),
        max_items_per_keyword=int(data.get("max_items_per_keyword", 10)),
        max_total_items=int(data.get("max_total_items", 0)),
        fetch_details=bool(data.get("fetch_details", True)),
        debug_snapshots=bool(data.get("debug_snapshots", False)),
        debug_dir=data.get("debug_dir", "data/debug"),
        system_prompt=data.get("system_prompt", SpyConfig.system_prompt),
    )
