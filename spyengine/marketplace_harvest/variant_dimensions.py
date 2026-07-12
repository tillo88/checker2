from __future__ import annotations

import re
from typing import Any
from .extractors import extract_specs_from_text
from .canonicalize import canonicalize_title
from .identifiers import extract_product_identifiers

_BRANDS = {
    "nvidia": ["nvidia", "geforce", "quadro"], "amd": ["amd", "radeon", "firepro"], "intel": ["intel", "arc", "core", "xeon"],
    "asus": ["asus", "rog", "tuf"], "msi": ["msi"], "gigabyte": ["gigabyte", "aorus"], "pny": ["pny"], "zotac": ["zotac"],
    "sapphire": ["sapphire"], "kingston": ["kingston", "hyperx"], "corsair": ["corsair", "vengeance"],
    "crucial": ["crucial", "micron"], "samsung": ["samsung"], "lg": ["lg"], "dell": ["dell", "alienware"],
    "lenovo": ["lenovo", "thinkpad", "legion"], "hp": ["hp", "hewlett", "omen", "zbook", "elitebook"], "google": ["google", "pixel"], "apple": ["apple", "iphone", "ipad", "macbook", "apple watch"],
}

def normalize_text_key(text: Any) -> str:
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")

def detect_brand(text: str) -> str:
    tl = f" {str(text or '').lower()} "
    # Product-line aliases should win over component/vendor words in the same title.
    if re.search(r"\b(hp|zbook|elitebook|omen)\b", tl): return "hp"
    if re.search(r"\b(thinkpad|lenovo|legion)\b", tl): return "lenovo"
    if re.search(r"\b(macbook|ipad|iphone|apple\s+watch|apple)\b", tl): return "apple"
    if re.search(r"\b(pixel|google)\b", tl): return "google"
    if re.search(r"\b(galaxy|samsung)\b", tl): return "samsung"
    for brand, aliases in _BRANDS.items():
        if any(f" {a.lower()} " in tl for a in aliases): return brand
    return ""

def infer_category(text: str, specs: dict[str, Any] | None = None) -> str:
    tl = str(text or "").lower(); specs = specs or extract_specs_from_text(text)
    if re.search(r"\b(rtx|gtx|quadro|radeon|rx\s?\d{3,4}|arc\s?a\d{3,4}|gpu|scheda\s+video|vram|gddr)\b", tl): return "technology_gpu"
    if re.search(r"\b(ddr[345]|sodimm|udimm|rdimm|ram|memoria)\b", tl): return "technology_ram"
    if re.search(r"\b(monitor|display|oled|ips|\bva\b|\btn\b|hz|ultrawide|1440p|4k)\b", tl) and ("hz" in specs or "inches" in specs or "monitor" in tl): return "technology_monitor"
    if re.search(r"\b(ipad|tablet|galaxy\s+tab|tab\s+[a-z0-9]|nokia\s+t20|lenovo\s+tab)\b", tl): return "technology_tablet"
    if re.search(r"\b(macbook|thinkpad|tp\s*t\d{3,4}|t\d{3,4}s?|latitude|elitebook|zbook|notebook|laptop|portatile|computer\s+portatile|hp\s+250r)\b", tl): return "technology_laptop"
    if re.search(r"\b(apple\s+watch|smartwatch|watch\s+series|watch\s+ultra|galaxy\s+watch)\b", tl): return "technology_smartwatch"
    if re.search(r"\b(iphone|galaxy\s+s\d|galaxy\s+z|pixel\s+\d|smartphone|telefono|cellulare)\b", tl): return "technology_smartphone"
    if re.search(r"\b(airpods?|earpods?|beats|bose|jabra|plantronics|quietcomfort|wh-\d|wf-\d|headphones?|cuffie|auricolari|sony\s+w[fh]|savi\s+\d|biz\s+\d)\b", tl): return "technology_audio"
    if re.search(r"\b(mouse|magic\s+mouse|keyboard|tastiera|pencil|pen|surface\s+pen|stylus|dock|docking|wd19tb|hub|charger|caricatore|cavo|cover|case|custodia|pellicola|screen protector|cuffie|headphones|accessori|accessory|hstnn)\b", tl): return "technology_accessory"
    if re.search(r"\b(ssd|nvme|m\.2|sata|hard\s*disk|hdd)\b", tl): return "technology_storage"
    if re.search(r"\b(cpu|processore|ryzen|core\s+i[3579]|xeon|threadripper)\b", tl): return "technology_cpu"
    if re.search(r"\b(trapano|avvitatore|batteria|18v|20v|utensile)\b", tl): return "tools_battery"
    return "unknown"


def _extract_gpu_family(text: str) -> str:
    pats = [r"\b(?:nvidia\s+)?(?:geforce\s+)?rtx\s*a?\s?\d{4}(?:\s*ti|\s*super)?\b", r"\b(?:nvidia\s+)?quadro\s+rtx\s+\d{4}\b", r"\brtx\s+a\s?\d{4}\b", r"\bradeon\s+(?:pro\s+)?(?:rx\s+)?[a-z0-9\s-]{2,18}\b", r"\bintel\s+arc\s+[a-z]\d{3,4}\b"]
    for pat in pats:
        m = re.search(pat, text or "", flags=re.I)
        if m:
            fam = re.sub(r"\s+", " ", m.group(0)).strip()
            fam = re.sub(r"\brtx\s+a\s?(\d{4})\b", r"RTX A\1", fam, flags=re.I)
            fam = re.sub(r"\brtx\s+(\d{4})\b", r"RTX \1", fam, flags=re.I)
            return fam.upper().replace("NVIDIA ", "").strip()
    return ""

def extract_family_name(text: str, category: str | None = None) -> str:
    category = category or infer_category(text)
    if category == "technology_gpu":
        fam = _extract_gpu_family(text)
        if fam: return fam
    if category == "technology_ram":
        brand = detect_brand(text); ddr = re.search(r"\bddr[345]\b", text or "", re.I); bits=[]
        if brand: bits.append(brand.upper())
        if ddr: bits.append(ddr.group(0).upper())
        bits.append("RAM"); return " ".join(bits)
    if category == "technology_monitor":
        brand = detect_brand(text); ids = extract_product_identifiers(text)
        for ident in ids:
            if ident.identifier_type in {"mpn", "sku_candidate"} and len(ident.value) >= 5: return f"{brand.upper()} {ident.value}".strip()
        return f"{brand.upper()} MONITOR".strip() if brand else ""
    title = canonicalize_title(str(text or ""))
    title = re.sub(r"\b\d+\s*(gb|tb|hz|v|volt|pollici|inch|inches)\b", " ", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip(" -|·")[:96]

def extract_variant_specs(text: str, category: str | None = None) -> dict[str, Any]:
    specs = extract_specs_from_text(text); category = category or infer_category(text, specs); out: dict[str, Any] = {}
    if category == "technology_gpu":
        vram = specs.get("vram_gb_values") or []
        if not vram and re.search(r"\b(rtx|quadro|radeon|gpu|scheda\s+video|gddr)\b", text or "", re.I):
            gb = specs.get("gb_values") or []
            vram = [v for v in gb if v in {2,3,4,6,8,10,11,12,16,20,24,32,40,48,64,80,96,128}]
        if vram: out["vram_gb"] = int(max(vram))
        return out
    if category == "technology_ram":
        ram = specs.get("ram_gb_values") or specs.get("gb_values") or []
        if ram: out["module_capacity_gb"] = int(max(ram))
        if specs.get("ddr"): out["ddr"] = specs["ddr"][0].upper()
        m = re.search(r"\b(\d+)\s*x\s*(\d+)\s*gb\b", text or "", re.I)
        if m:
            out["module_count"] = int(m.group(1)); out["module_capacity_gb"] = int(m.group(2)); out["kit_total_gb"] = int(m.group(1)) * int(m.group(2))
        if re.search(r"\bsodimm|so-dimm|laptop|notebook|portatile\b", text or "", re.I): out["form_factor"] = "SODIMM"
        elif re.search(r"\budimm|desktop\b", text or "", re.I): out["form_factor"] = "UDIMM"
        if re.search(r"\becc\b", text or "", re.I): out["ecc"] = True
        return out
    if category == "technology_monitor":
        if specs.get("inches"): out["size_inches"] = max(specs["inches"])
        if specs.get("hz"): out["refresh_hz"] = int(max(specs["hz"]))
        m = re.search(r"\b(1920x1080|2560x1440|3440x1440|3840x2160|4k|qhd|fhd|uhd)\b", text or "", re.I)
        if m: out["resolution"] = m.group(1).upper()
        return out
    return specs

def variant_key_for(category: str, brand: str, family_name: str, variant_specs: dict[str, Any]) -> str:
    bits = [category or "unknown", brand or "unknown", normalize_text_key(family_name)]
    if category == "technology_gpu" and variant_specs.get("vram_gb"): bits.append(f"vram_{int(variant_specs['vram_gb'])}gb")
    elif category == "technology_ram":
        for k, fmt in [("ddr", lambda v: str(v).lower()), ("module_capacity_gb", lambda v: f"{int(v)}gb"), ("module_count", lambda v: f"{int(v)}x"), ("form_factor", normalize_text_key)]:
            if variant_specs.get(k): bits.append(fmt(variant_specs[k]))
    elif category == "technology_monitor":
        if variant_specs.get("size_inches"): bits.append(f"{str(variant_specs['size_inches']).replace('.', '_')}in")
        if variant_specs.get("refresh_hz"): bits.append(f"{int(variant_specs['refresh_hz'])}hz")
        if variant_specs.get("resolution"): bits.append(normalize_text_key(variant_specs["resolution"]))
    else:
        for k in sorted(variant_specs):
            v = variant_specs[k]
            if isinstance(v, (str, int, float, bool)): bits.append(f"{normalize_text_key(k)}_{normalize_text_key(v)}")
    return ":".join([b for b in bits if b])

def analyze_listing_product(text: str) -> dict[str, Any]:
    canonical_input = canonicalize_title(str(text or ""))
    if canonical_input:
        text = canonical_input
    specs = extract_specs_from_text(text); category = infer_category(text, specs); brand = detect_brand(text); family = extract_family_name(text, category); variant_specs = extract_variant_specs(text, category); identifiers = extract_product_identifiers(text)
    ambiguity = "resolved" if variant_specs or identifiers else "family_only"
    if category == "technology_gpu" and family and not variant_specs.get("vram_gb"): ambiguity = "variant_ambiguous"
    variant_label = family
    if category == "technology_gpu" and variant_specs.get("vram_gb"): variant_label = f"{family} {int(variant_specs['vram_gb'])}GB"
    elif category == "technology_ram" and variant_specs.get("module_capacity_gb"): variant_label = f"{family} {int(variant_specs['module_capacity_gb'])}GB"
    return {"category": category, "brand": brand, "family_name": family, "family_key": f"{category}:{brand or 'unknown'}:{normalize_text_key(family)}", "variant_name": variant_label, "variant_key": variant_key_for(category, brand, family, variant_specs), "variant_specs": variant_specs, "identifiers": identifiers, "ambiguity_status": ambiguity, "confidence": 0.75 if category != "unknown" and family else 0.35}
