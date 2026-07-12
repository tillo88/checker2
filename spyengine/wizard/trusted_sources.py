from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any


SOURCE_PROFILE_STORE = Path(os.environ.get("SPYENGINE_SOURCE_PROFILE_STORE", "data/knowledge_cache/source_profiles.json"))


def clean(value: Any) -> str:
    s = str(value or "").lower()
    s = s.replace("×", "x")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def slugify(value: str) -> str:
    s = clean(value)
    s = re.sub(r"[^a-z0-9àèéìòù]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:48] or "generic"


def has_term(text: str, term: str) -> bool:
    """
    Safe category term matching.

    Important:
    - short technical tokens like "va" or "hz" must match as words/tokens only
      so "van bene" does NOT trigger monitor/VA.
    - longer phrases can be substring matches.
    """
    t = clean(text)
    q = clean(term)
    if not q:
        return False

    if len(q) <= 3 or re.fullmatch(r"[a-z0-9.+-]+", q):
        return re.search(rf"(?<![a-z0-9]){re.escape(q)}(?![a-z0-9])", t) is not None

    return q in t


def has_any(text: str, terms: list[str]) -> bool:
    return any(has_term(text, term) for term in terms)


SOURCE_PROFILES: dict[str, dict[str, Any]] = {
    "technology_ram": {
        "label": "RAM / memoria",
        "domains": ["kingston.com", "crucial.com", "corsair.com", "gskill.com", "techpowerup.com"],
        "notes": [
            "Per RAM, distinguere con molta attenzione generazione DDR, formato desktop/notebook e presenza ECC/RDIMM/Registered.",
            "UDIMM desktop, SO-DIMM notebook, ECC/RDIMM/server sono categorie diverse anche se tutte possono essere DDR4.",
            "Le capacità inferiori al minimo richiesto non devono essere trattate come alternative valide.",
        ],
        "query_templates": [
            "site:kingston.com {query} RAM DDR specifications",
            "site:crucial.com {query} memory specifications",
            "site:corsair.com {query} memory DDR",
            "site:gskill.com {query} DDR memory",
            "site:techpowerup.com {query} RAM DDR",
        ],
    },
    "technology_gpu": {
        "label": "GPU / schede video",
        "domains": ["techpowerup.com", "nvidia.com", "amd.com", "videocardz.com"],
        "notes": [
            "Per specifiche GPU, preferisci database tecnici e pagine produttore rispetto a blog/gossip.",
            "TechPowerUp è utile come fonte tecnica per modelli GPU e specifiche, ma il wizard deve comunque trattare i risultati come hint.",
            "Per richieste 'almeno N GB VRAM', cerca anche tagli superiori a N e modelli noti con quei tagli.",
        ],
        "query_templates": [
            "site:techpowerup.com/gpu-specs {query}",
            "site:nvidia.com {query} VRAM specifications",
            "site:amd.com {query} VRAM specifications",
            "site:videocardz.com {query} VRAM",
        ],
    },
    "technology_cpu": {
        "label": "CPU / processori",
        "domains": ["techpowerup.com", "intel.com", "amd.com", "cpu-world.com"],
        "notes": [
            "Per CPU, preferisci database tecnici e pagine produttore.",
            "Fai attenzione a socket, generazione, TDP e compatibilità scheda madre.",
        ],
        "query_templates": [
            "site:techpowerup.com/cpu-specs {query}",
            "site:intel.com {query} specifications",
            "site:amd.com {query} specifications",
            "site:cpu-world.com {query}",
        ],
    },
    "technology_ssd": {
        "label": "SSD / NVMe / storage",
        "domains": ["techpowerup.com", "tomshardware.com", "anandtech.com", "pcpartpicker.com"],
        "notes": [
            "Per SSD/NVMe, controlla capacità, formato, interfaccia, generazione PCIe e presenza dissipatore.",
            "Non confondere enclosure/adattatori/box esterni con SSD veri.",
        ],
        "query_templates": [
            "site:techpowerup.com {query} SSD specifications",
            "site:pcpartpicker.com {query} SSD",
            "site:tomshardware.com {query} SSD review specs",
            "site:anandtech.com {query} SSD",
        ],
    },
    "technology_monitor": {
        "label": "Monitor / pannelli",
        "domains": ["tftcentral.co.uk", "rtings.com", "displayspecifications.com", "panelook.com"],
        "notes": [
            "Per monitor, fonti utili sono database/review tecniche su pannello, refresh, risoluzione, HDR, input lag e VRR.",
            "Fai attenzione a sigle modello quasi identiche: una lettera finale può cambiare pannello o refresh.",
        ],
        "query_templates": [
            "site:tftcentral.co.uk {query}",
            "site:rtings.com/monitor {query}",
            "site:displayspecifications.com {query}",
            "site:panelook.com {query}",
        ],
    },
    "vehicle_tires": {
        "label": "Auto / gomme / cerchi",
        "domains": ["wheel-size.com", "tiresize.com", "oponeo.it", "pirelli.com"],
        "notes": [
            "Per gomme/cerchi, le misure possono variare in base ad anno, allestimento, cerchio e libretto.",
            "Usa le fonti come hint e mantieni una nota di verifica compatibilità.",
        ],
        "query_templates": [
            "site:wheel-size.com {query} tire size",
            "site:tiresize.com {query} tire size",
            "site:oponeo.it {query} misura pneumatici",
            "site:pirelli.com {query} pneumatici",
        ],
    },
    "home_window_coverings": {
        "label": "Casa / tapparelle / serrande / tende",
        "domains": ["leroymerlin.it", "manomano.it", "bricoio.it", "bticino.it"],
        "notes": [
            "Per tapparelle/serrande/tende, contano molto misure, materiale, compatibilità con motore/rullo/guide e stato di usura.",
            "Distinguere prodotto completo da ricambi/accessori come motori, telecomandi, cinghie, guide o cassonetti.",
            "Se la richiesta dipende da misura o compatibilità, usare il web come hint e chiedere/verificare se incerto.",
        ],
        "query_templates": [
            "site:leroymerlin.it {query} tapparella specifiche misure",
            "site:manomano.it {query} tapparella misure materiale",
            "site:bricoio.it {query} tapparella",
            "site:bticino.it {query} tapparelle motore compatibilità",
        ],
    },
    "home_generic": {
        "label": "Casa / arredamento / bricolage",
        "domains": ["ikea.com", "leroymerlin.it", "manomano.it", "bricoio.it"],
        "notes": [
            "Per casa/arredamento contano misure, materiale, colore, stato e ritiro/spedizione.",
            "Set/lotti possono essere validi; ricambi/accessori vanno trattati come distractor salvo richiesta esplicita.",
        ],
        "query_templates": [
            "site:ikea.com {query}",
            "site:leroymerlin.it {query} misure materiale",
            "site:manomano.it {query}",
            "site:bricoio.it {query}",
        ],
    },
    "garden": {
        "label": "Giardino",
        "domains": ["leroymerlin.it", "manomano.it", "stihl.it", "husqvarna.com"],
        "notes": [
            "Per giardino, distinguere macchina completa da ricambi/accessori/batterie/lame.",
            "Guasto, non funzionante e da riparare sono normalmente hard reject salvo richiesta esplicita.",
        ],
        "query_templates": [
            "site:leroymerlin.it {query} giardino",
            "site:manomano.it {query} giardino",
            "site:stihl.it {query} specifiche",
            "site:husqvarna.com {query} specifiche",
        ],
    },
    "outdoor": {
        "label": "Outdoor / campeggio / trekking",
        "domains": ["decathlon.it", "rei.com", "outdoorgearlab.com", "bergfreunde.eu"],
        "notes": [
            "Per outdoor contano taglia, litri, stagionalità, peso, materiale e condizioni.",
            "Accessori/custodie/ricambi sono spesso distractor, non prodotto principale.",
        ],
        "query_templates": [
            "site:decathlon.it {query}",
            "site:rei.com {query} specs",
            "site:outdoorgearlab.com {query}",
            "site:bergfreunde.eu {query}",
        ],
    },
    "tools": {
        "label": "Utensili / fai-da-te",
        "domains": ["bosch-professional.com", "makita.it", "dewalt.it", "manomano.it"],
        "notes": [
            "Per utensili, distinguere utensile completo da sola batteria/caricatore/valigetta/accessorio.",
            "Compatibilità batteria/voltaggio e condizioni sono spesso decisive.",
        ],
        "query_templates": [
            "site:bosch-professional.com {query} specifiche",
            "site:makita.it {query} specifiche",
            "site:dewalt.it {query} specifiche",
            "site:manomano.it {query}",
        ],
    },
    "technology_generic": {
        "label": "Tecnologia generica",
        "domains": ["techpowerup.com", "pcpartpicker.com", "notebookcheck.net", "rtings.com"],
        "notes": [
            "Per tecnologia generica, preferisci database tecnici, produttori e review misurative.",
            "Non copiare compatibilità non verificata come hard reject.",
        ],
        "query_templates": [
            "site:techpowerup.com {query} specifications",
            "site:pcpartpicker.com {query}",
            "site:notebookcheck.net {query}",
            "site:rtings.com {query}",
        ],
    },
}


def load_learned_profiles() -> dict[str, dict[str, Any]]:
    if not SOURCE_PROFILE_STORE.exists():
        return {}
    try:
        data = json.loads(SOURCE_PROFILE_STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_learned_profiles(data: dict[str, dict[str, Any]]) -> None:
    SOURCE_PROFILE_STORE.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_PROFILE_STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_profile_terms(user_description: str, limit: int = 12) -> list[str]:
    """
    Extract stable product/category terms for on-demand learning.
    This is intentionally simple: enough to match future similar descriptions,
    not meant to be perfect taxonomy.
    """
    t = clean(user_description)
    stop = {
        "cerco", "cerca", "voglio", "vorrei", "possibilmente", "solo", "anche",
        "almeno", "minimo", "massimo", "budget", "prezzo", "euro", "eur",
        "con", "senza", "per", "del", "della", "dello", "degli", "delle", "da",
        "vendita", "vendere", "separatamente", "controlla", "comunque",
        "buono", "buona", "condizione", "condizioni", "nuovo", "usato",
    }

    # Preserve multi-word product nouns first.
    phrases = [
        "scheda madre", "schede madri", "scheda video", "trapano avvitatore",
        "trapano a batteria", "pc completo", "computer intero", "tapparella elettrica",
        "tapparelle elettriche", "monitor oled", "ram ddr4", "ram ddr5",
    ]
    terms = []
    for phrase in phrases:
        if phrase in t:
            terms.append(phrase)

    # Tokens, including useful technical alphanumerics like b550, am4, 18v, 240hz.
    for token in re.findall(r"[a-z0-9àèéìòù.+-]{3,}", t):
        if token in stop:
            continue
        if re.fullmatch(r"\d+", token):
            continue
        terms.append(token)

    return dedup_list(terms, limit)


def learned_profile_score(user_description: str, profile_data: dict[str, Any]) -> int:
    t = clean(user_description)
    terms = list(profile_data.get("match_terms") or [])
    if not terms:
        # Backward compatibility: use label/domains weakly.
        terms = re.findall(r"[a-z0-9àèéìòù]{4,}", clean(profile_data.get("label", "")))

    score = 0
    for term in terms:
        q = clean(term)
        if not q:
            continue
        if " " in q:
            if q in t:
                score += 4
        elif has_term(t, q):
            score += 2
    return score


def detect_learned_source_profile(user_description: str, min_score: int = 4) -> str | None:
    learned = load_learned_profiles()
    best_key = None
    best_score = 0
    for key, data in learned.items():
        if not isinstance(data, dict):
            continue
        score = learned_profile_score(user_description, data)
        if score > best_score:
            best_key = key
            best_score = score

    if best_key and best_score >= min_score:
        return best_key
    return None


def learn_profile_from_description(profile: str, user_description: str) -> dict[str, Any]:
    """
    Ensure every non-generic category/profile gets persisted, even before web results.
    This makes categories improve over time without hand-written micro-patches.
    """
    if not profile or profile == "generic":
        return {}

    data = load_learned_profiles()
    current = data.get(profile, {}) if isinstance(data.get(profile), dict) else {}
    base = SOURCE_PROFILES.get(profile) or build_dynamic_source_profile(user_description, profile)

    terms = extract_profile_terms(user_description)
    old_terms = list(current.get("match_terms") or [])

    domains = dedup_list(list(base.get("domains") or []) + list(current.get("domains") or []), 20)
    notes = dedup_list(list(base.get("notes") or []) + list(current.get("notes") or []), 20)
    query_templates = dedup_list(list(base.get("query_templates") or []) + list(current.get("query_templates") or []), 20)

    examples = list(current.get("examples") or [])
    sample = extract_search_subject(user_description)
    if sample and sample not in examples:
        examples.append(sample)
    examples = examples[-8:]

    count = int(current.get("seen_count") or 0) + 1

    payload = {
        "label": current.get("label") or base.get("label") or profile,
        "domains": domains,
        "notes": notes,
        "query_templates": query_templates,
        "match_terms": dedup_list(old_terms + terms, 30),
        "examples": examples,
        "seen_count": count,
        "dynamic": bool(base.get("dynamic") or profile.startswith("dynamic_")),
        "learned_at": current.get("learned_at") or time.time(),
        "updated_at": time.time(),
    }

    data[profile] = payload
    save_learned_profiles(data)
    return payload




def get_source_profile(profile: str, user_description: str = "") -> dict[str, Any]:
    if profile in SOURCE_PROFILES:
        base = dict(SOURCE_PROFILES[profile])
    else:
        base = build_dynamic_source_profile(user_description, profile)

    learned = load_learned_profiles().get(profile)
    if isinstance(learned, dict):
        merged = dict(base)
        merged["domains"] = dedup_list(list(base.get("domains") or []) + list(learned.get("domains") or []), 12)
        merged["notes"] = dedup_list(list(base.get("notes") or []) + list(learned.get("notes") or []), 12)
        merged["query_templates"] = dedup_list(list(base.get("query_templates") or []) + list(learned.get("query_templates") or []), 12)
        merged["learned_at"] = learned.get("learned_at")
        return merged

    return base


def dedup_list(values: list[Any], limit: int = 20) -> list[str]:
    out = []
    seen = set()
    for value in values or []:
        s = str(value or "").strip()
        k = clean(s)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def detect_dynamic_category(user_description: str) -> tuple[str, str]:
    t = clean(user_description)

    groups = [
        ("technology_motherboard", "Tecnologia / schede madri", ["scheda madre", "schede madri", "motherboard", "mainboard", "am4", "am5", "lga", "b450", "b550", "x570", "b650", "x670", "z690", "z790", "atx", "matx", "mini-itx"]),
        ("home_window_coverings", "Casa / tapparelle / serrande / tende", ["tapparella", "tapparelle", "serranda", "serrande", "avvolgibile", "avvolgibili", "persiana", "persiane", "veneziana", "zanzariera"]),
        ("home_generic", "Casa / arredamento / bricolage", ["casa", "arredamento", "mobile", "sedia", "tavolo", "divano", "armadio", "letto", "materasso", "lampada", "infissi", "finestra", "porta"]),
        ("garden", "Giardino", ["giardino", "tosaerba", "decespugliatore", "motosega", "tagliasiepi", "soffiatore", "irrigazione", "vaso"]),
        ("outdoor", "Outdoor / campeggio / trekking", ["campeggio", "camping", "trekking", "tenda", "zaino", "sacco a pelo", "scarponi", "survival", "bushcraft"]),
        ("tools", "Utensili / fai-da-te", ["trapano", "avvitatore", "smerigliatrice", "compressore", "utensile", "bosch", "makita", "dewalt"]),
    ]

    for key, label, terms in groups:
        if has_any(t, terms):
            return key, label

    # Create a dynamic slug from the most meaningful words.
    stop = {
        "cerco", "cerca", "voglio", "vorrei", "con", "per", "del", "della", "dello", "degli",
        "delle", "solo", "minimo", "massimo", "budget", "euro", "prezzo", "modello",
        "usato", "nuovo", "buono", "buona", "condizione", "condizioni",
    }
    words = [w for w in re.findall(r"[a-z0-9àèéìòù]{4,}", t) if w not in stop]
    label_words = words[:4] or ["generico"]
    label = " / ".join(label_words)
    return f"dynamic_{slugify('_'.join(label_words))}", label


def build_dynamic_source_profile(user_description: str, profile: str = "generic") -> dict[str, Any]:
    detected_key, label = detect_dynamic_category(user_description)
    if profile == "generic" or profile.startswith("dynamic_"):
        profile = detected_key

    subject = extract_search_subject(user_description)
    return {
        "label": label,
        "domains": [],
        "notes": [
            f"Profilo fonti dinamico creato per: {label}.",
            "Prima cerca fonti autorevoli o database di settore; poi usa risultati generici solo come fallback.",
            "Se le fonti non sono chiare, non inventare hard reject: mantieni la verifica come nota/AI review.",
        ],
        "query_templates": [
            "migliori siti database specifiche {query}",
            "fonti autorevoli specifiche {query}",
            "database compatibilità misure {query}",
            "recensioni tecniche specifiche {query}",
        ],
        "dynamic": True,
        "detected_profile": profile,
        "subject": subject,
    }


def learn_sources_from_results(profile: str, user_description: str, results: list[dict], max_domains: int = 8) -> list[str]:
    if profile in SOURCE_PROFILES:
        # Still allow adding extra learned domains, but built-ins remain primary.
        pass

    bad_domains = {
        "duckduckgo.com", "google.com", "bing.com", "yahoo.com",
        "facebook.com", "instagram.com", "tiktok.com", "youtube.com",
        "pinterest.com", "reddit.com", "x.com", "twitter.com",
        "amazon.it", "amazon.com", "ebay.it", "ebay.com", "subito.it", "vinted.it", "wallapop.com",
    }

    domains = []
    for result in results or []:
        url = str(result.get("url") or "")
        if not url:
            continue
        try:
            host = urllib.parse.urlparse(url).netloc.lower()
        except Exception:
            continue
        host = host[4:] if host.startswith("www.") else host
        if not host or host in bad_domains:
            continue
        # Avoid very broad hosts if possible.
        if host.count(".") > 3:
            continue
        domains.append(host)

    domains = dedup_list(domains, max_domains)
    if not domains:
        return []

    data = load_learned_profiles()
    current = data.get(profile, {})
    old_domains = list(current.get("domains") or [])
    old_notes = list(current.get("notes") or [])
    label = get_source_profile(profile, user_description).get("label", profile)

    data[profile] = {
        "label": label,
        "domains": dedup_list(old_domains + domains, 16),
        "notes": dedup_list(old_notes + [f"Fonti apprese automaticamente per {label}; usarle come hint, non come verità assoluta."], 12),
        "query_templates": dedup_list(
            list(current.get("query_templates") or [])
            + [f"site:{domain} {{query}}" for domain in domains[:6]],
            16,
        ),
        "match_terms": dedup_list(list(current.get("match_terms") or []) + extract_profile_terms(user_description), 30),
        "examples": list(current.get("examples") or [])[-8:],
        "seen_count": int(current.get("seen_count") or 0),
        "dynamic": bool(current.get("dynamic") or profile.startswith("dynamic_")),
        "learned_at": current.get("learned_at") or time.time(),
        "updated_at": time.time(),
    }
    save_learned_profiles(data)
    return domains


def detect_source_profile(user_description: str, need: dict | None = None) -> str:
    t = clean(user_description)
    domain = (need or {}).get("domain") or ""

    if domain in SOURCE_PROFILES:
        return domain

    if has_any(t, ["ram", "memoria", "ddr", "sodimm", "so-dimm", "rdimm", "udimm"]):
        return "technology_ram"

    if has_any(t, ["scheda video", "gpu", "vga", "vram", "rtx", "radeon", "quadro", "geforce"]):
        return "technology_gpu"

    if has_any(t, ["cpu", "processore", "ryzen", "intel core", "xeon", "threadripper"]):
        return "technology_cpu"

    if has_any(t, ["ssd", "nvme", "m.2", "sata", "gen4", "gen5", "pcie"]):
        return "technology_ssd"

    if has_any(t, ["scheda madre", "schede madri", "motherboard", "mainboard", "am4", "am5", "b450", "b550", "x570", "b650", "x670", "z690", "z790"]):
        return "technology_motherboard"

    if has_any(t, ["monitor", "schermo", "display", "refresh", "hz", "oled", "ips", "va", "ultrawide"]):
        return "technology_monitor"

    if has_any(t, ["gomme", "pneumatici", "cerchi", "ruote"]) and has_any(t, ["auto", "macchina", "yaris", "golf", "panda", "fiesta", "clio"]):
        return "vehicle_tires"

    learned = detect_learned_source_profile(user_description)
    if learned:
        return learned

    key, _label = detect_dynamic_category(user_description)
    if key != "dynamic_generico":
        return key

    if has_any(t, ["scheda madre", "notebook", "tablet", "iphone", "android"]):
        return "technology_generic"

    return "generic"


def compact_terms(values: list[str], limit: int = 10) -> str:
    return " ".join(dedup_list([v for v in values if v], limit))


def compact_terms(values: list[str], limit: int = 10) -> str:
    return " ".join(dedup_list([v for v in values if v], limit))


def extract_search_subject(user_description: str) -> str:
    """
    Build a broad search subject for knowledge/web.

    Principle:
    - Search broad: object/category + stable technical family.
    - Filter later: capacities, thresholds, budgets, exclusions, variants.

    This function is intentionally NOT the same as marketplace search keywords.
    Marketplace queries may include 32GB/16GB/18V/etc.; knowledge/source discovery
    should usually not.
    """
    raw = str(user_description or "").strip()
    t = clean(raw)
    compact = t.replace(" ", "")

    # RAM: broad family only. Capacity/ECC/SODIMM are filters, not source-query terms.
    if has_any(t, ["ram", "memoria", "ddr", "sodimm", "so-dimm", "rdimm", "udimm"]):
        terms = ["ram"]
        for gen in ["ddr5", "ddr4", "ddr3", "ddr2"]:
            if gen in compact:
                terms.append(gen)
                break

        if has_any(t, ["desktop", "fisso", "pc fisso", "udimm", "dimm"]):
            terms.append("desktop")
        elif has_any(t, ["laptop", "notebook", "portatile", "sodimm", "so-dimm"]):
            terms.append("sodimm")

        return compact_terms(terms, 5)

    # GPU: broad family. Minimum VRAM is filtered after results, not baked into source query.
    if has_any(t, ["scheda video", "gpu", "vga", "vram", "rtx", "radeon", "quadro", "geforce"]):
        terms = ["gpu"]
        if "vram" in t or re.search(r"\d+\s*gb", t):
            terms.append("vram")
        for token in ["rtx", "radeon", "quadro", "geforce"]:
            if has_term(t, token):
                terms.append(token)
        return compact_terms(terms, 5)

    # Motherboards: socket/chipset/form-factor are useful broad family terms.
    # They are not just filters; they define the product family/source pages.
    if has_any(t, ["scheda madre", "schede madri", "motherboard", "mainboard", "am4", "am5", "b550", "x570", "z790"]):
        terms = ["scheda madre"]
        for token in ["am4", "am5", "lga1700", "lga 1700", "b450", "b550", "x570", "b650", "x670", "z690", "z790", "atx", "matx", "micro atx", "mini itx", "ryzen", "intel"]:
            if token in t:
                terms.append(token)
        return compact_terms(terms, 8)

    # Monitors: keep class/family; exact refresh/size are filters unless they identify the family.
    if has_any(t, ["monitor", "schermo", "display", "oled", "ips", "refresh", "hz", "ultrawide"]):
        terms = ["monitor"]
        for token in ["oled", "ips", "va", "tn", "ultrawide", "curvo", "hdr"]:
            if has_term(t, token):
                terms.append(token)
        for token in ["4k", "1440p", "2k", "1080p"]:
            if token in t:
                terms.append(token)
        return compact_terms(terms, 7)

    # Tools / cordless examples: keep product + cordless/battery class.
    # Voltage/amperage are filters after result collection.
    if has_any(t, ["trapano", "avvitatore", "smerigliatrice", "tassellatore", "utensile"]):
        if "trapano" in t and "avvitatore" in t:
            base = "trapano avvitatore"
        elif "trapano" in t:
            base = "trapano"
        elif "avvitatore" in t:
            base = "avvitatore"
        elif "smerigliatrice" in t:
            base = "smerigliatrice"
        elif "tassellatore" in t:
            base = "tassellatore"
        else:
            base = "utensile"

        terms = [base]
        if has_any(t, ["batteria", "batterie", "cordless"]):
            terms.append("a batteria")
        return compact_terms(terms, 4)

    # Home / shutters: product family.
    if has_any(t, ["tapparella", "tapparelle", "serranda", "serrande", "avvolgibile", "persiana", "zanzariera"]):
        terms = []
        for token in ["tapparelle", "tapparella", "serrande", "serranda", "avvolgibile", "persiana", "zanzariera"]:
            if has_term(t, token):
                terms.append(token)
        if has_any(t, ["elettrica", "elettriche", "motore", "motorizzata", "motorizzate"]):
            terms.append("motorizzata")
        return compact_terms(terms or ["tapparelle"], 5)

    # Generic broad fallback: a few stable nouns/tokens only.
    s = raw
    s = re.sub(r"\b(budget|prezzo massimo|max|massimo)\s*\d+[.,]?\d*\s*(?:€|euro|eur)?", " ", s, flags=re.I)
    s = re.sub(r"\b\d+[.,]?\d*\s*(?:€|euro|eur)\b", " ", s, flags=re.I)
    low = clean(s)

    stop = {
        "cerco", "cerca", "voglio", "vorrei", "possibilmente", "solo", "anche",
        "almeno", "minimo", "massimo", "budget", "prezzo", "euro", "eur",
        "con", "senza", "per", "del", "della", "dello", "degli", "delle", "da",
        "controllare", "controlla", "comunque", "vendita", "vendere", "pezzi",
        "bene", "stesso", "principio", "offerta", "vicini",
    }
    words = []
    for w in re.findall(r"[a-z0-9àèéìòù.+-]{3,}", low):
        if w in stop:
            continue
        if re.fullmatch(r"\d+", w):
            continue
        # Avoid pure capacity/threshold tokens in broad source query.
        if re.fullmatch(r"\d+(gb|tb|v|volt|hz|w|ah|mah)", w):
            continue
        words.append(w)

    return compact_terms(words, 6) or raw[:80]




def trusted_source_notes(profile: str, user_description: str = "") -> list[str]:
    data = get_source_profile(profile, user_description)
    return list(data.get("notes") or [])


def trusted_source_domains(profile: str, user_description: str = "") -> list[str]:
    data = get_source_profile(profile, user_description)
    return list(data.get("domains") or [])


def extract_min_thresholds_for_sources(user_description: str) -> list[dict]:
    t = clean(user_description)
    patterns = [
        r"(?:almeno|minimo|>=|non meno di|da almeno)\s*(\d+(?:[.,]\d+)?)\s*(v|volt|ah|mah|w|watt|hz|kg|l|litri|mm|cm|gb|tb)\b",
        r"(\d+(?:[.,]\d+)?)\s*(v|volt|ah|mah|w|watt|hz|kg|l|litri|mm|cm|gb|tb)\s*(?:o più|in su|minimo|almeno)\b",
    ]
    def variants(value: int, unit: str) -> list[int]:
        tables = {
            "v": [10, 12, 14, 18, 20, 24, 36, 40, 48, 54, 60],
            "volt": [10, 12, 14, 18, 20, 24, 36, 40, 48, 54, 60],
            "ah": [1, 2, 3, 4, 5, 6, 8, 10, 12],
            "mah": [1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000],
            "w": [300, 400, 500, 600, 800, 1000, 1200, 1500, 2000],
            "watt": [300, 400, 500, 600, 800, 1000, 1200, 1500, 2000],
            "hz": [60, 75, 100, 120, 144, 165, 180, 240, 300, 360, 500],
            "gb": [4, 8, 12, 16, 24, 32, 48, 64, 80, 96, 128],
            "tb": [1, 2, 4, 8, 12, 16, 20, 24],
        }
        seq = tables.get(unit, [])
        out = [x for x in seq if x >= value]
        if value not in out:
            out.insert(0, value)
        return out[:6]

    out = []
    seen = set()
    for pattern in patterns:
        for m in re.finditer(pattern, t):
            try:
                value = int(float(m.group(1).replace(",", ".")))
            except Exception:
                continue
            unit = clean(m.group(2))
            key = (value, unit)
            if key in seen:
                continue
            seen.add(key)
            out.append({"value": value, "unit": unit, "variants": variants(value, unit)})
    return out


def product_hint_for_sources(user_description: str) -> str:
    t = clean(user_description)
    for term in [
        "trapano avvitatore", "trapano", "avvitatore", "smerigliatrice", "tassellatore",
        "decespugliatore", "motosega", "tosaerba", "monitor", "scheda video", "gpu", "ssd",
    ]:
        if term in t:
            return term
    words = [w for w in re.findall(r"[a-z0-9àèéìòù]{4,}", t) if w not in {"cerco", "cerca", "almeno", "minimo", "budget", "euro"}]
    return " ".join(words[:3]) or extract_search_subject(user_description)


def trusted_source_queries(user_description: str, need: dict | None = None, max_queries: int = 8) -> list[str]:
    profile = detect_source_profile(user_description, need)
    data = get_source_profile(profile, user_description)

    subject = extract_search_subject(user_description)
    min_vram = (need or {}).get("min_vram_gb")

    # GPU threshold searches are broad-first:
    # "almeno 24GB VRAM" is a post-filter, not a query term.
    if profile == "technology_gpu" and min_vram:
        q = [
            "TechPowerUp GPU specs VRAM",
            "TechPowerUp GPU database VRAM",
            "NVIDIA GPU VRAM specifications",
            "AMD GPU VRAM specifications",
            "VideoCardz GPU VRAM",
            "GPU VRAM models",
            "schede video VRAM modelli",
            "professional GPU VRAM specifications",
            "site:techpowerup.com/gpu-specs VRAM",
            "site:nvidia.com GPU VRAM specifications",
            "site:amd.com GPU VRAM specifications",
        ]
        return dedup_list(q, max_queries)

    # Generic numeric thresholds are searched broad-first.
    # Example: "trapano almeno 18v" -> search "trapano a batteria", then post-filter >=18v.
    # This avoids over-constraining the search with 18v/20v/24v/etc all as separate searches.
    thresholds = extract_min_thresholds_for_sources(user_description)
    if thresholds and profile not in {"technology_gpu"}:
        product = product_hint_for_sources(user_description)
        queries = []
        domains = data.get("domains") or []
        for domain in domains[:3]:
            queries.append(f"site:{domain} {product}")
            queries.append(f"site:{domain} {product} specifiche")
            if any(th.get("unit") in {"v", "volt", "ah", "mah"} for th in thresholds):
                queries.append(f"site:{domain} {product} batteria")
        queries.append(product)
        queries.append(f"{product} a batteria")
        queries.append(f"{product} cordless")
        queries.append(f"{product} specifiche")
        return dedup_list(queries, max_queries)

    queries = []
    for template in data.get("query_templates") or []:
        q = template.format(query=subject)
        q = re.sub(r"\s+", " ", q).strip()
        if q:
            queries.append(q)
        if len(queries) >= max_queries:
            break

    return queries


def source_discovery_queries(user_description: str, need: dict | None = None, max_queries: int = 3) -> list[str]:
    """
    Fallback discovery: use after trusted profile queries, especially for dynamic profiles.
    """
    profile = detect_source_profile(user_description, need)
    subject = extract_search_subject(user_description)
    data = get_source_profile(profile, user_description)
    label = data.get("label", profile)

    if profile == "generic":
        return [
            f"best database specifications {subject}",
            f"technical specs database {subject}",
            f"compatibility database {subject}",
        ][:max_queries]

    return [
        f"migliori siti specifiche {label} {subject}",
        f"fonti autorevoli database {label} {subject}",
        f"{subject} technical specifications database",
    ][:max_queries]
