from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .trusted_sources import (
    detect_source_profile,
    get_source_profile,
    learn_profile_from_description,
    learn_sources_from_results,
    source_discovery_queries,
    trusted_source_domains,
    trusted_source_notes,
    trusted_source_queries,
)


CACHE_DIR = Path(os.environ.get("SPYENGINE_KNOWLEDGE_CACHE", "data/knowledge_cache"))
DEFAULT_TIMEOUT = float(os.environ.get("SPYENGINE_WEB_TIMEOUT", "8"))
CACHE_TTL_DAYS = int(os.environ.get("SPYENGINE_KNOWLEDGE_TTL_DAYS", "90"))
CACHE_SCHEMA_VERSION = "M8.62"


def _env_int(name: str, default: int, minimum: int = 1, maximum: int = 500) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


# Small prompt, larger local knowledge database.
# The wizard should not stop learning after 5 search results; it should collect enough
# broad source data, then filter for the current user threshold before building the prompt.
KNOWLEDGE_PROMPT_RESULTS = _env_int("SPYENGINE_KNOWLEDGE_PROMPT_RESULTS", 6, 1, 30)
KNOWLEDGE_PER_QUERY_RESULTS = _env_int("SPYENGINE_KNOWLEDGE_PER_QUERY_RESULTS", 8, 1, 25)
KNOWLEDGE_COLLECT_RESULTS = _env_int("SPYENGINE_KNOWLEDGE_COLLECT_RESULTS", 40, 5, 300)
KNOWLEDGE_FILTERED_TARGET = _env_int("SPYENGINE_KNOWLEDGE_FILTERED_TARGET", 16, 3, 100)
KNOWLEDGE_CACHE_RESULT_CAP = _env_int("SPYENGINE_KNOWLEDGE_CACHE_RESULT_CAP", 200, 20, 1000)


def clean(value: Any) -> str:
    s = str(value or "").lower()
    s = s.replace("×", "x")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def cache_key(value: str) -> str:
    return hashlib.sha256(clean(value).encode("utf-8")).hexdigest()[:24]


def cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"

def canonical_knowledge_subject(user_description: str, need: dict | None = None, source_profile: str = "") -> str:
    """
    Stable subject key for cache reuse.

    Example:
    - "GPU almeno 24GB VRAM" and "GPU oltre 16GB VRAM" both map to the same
      GPU/VRAM catalog, then threshold filtering is applied per request.
    """
    need = need or {}
    t = clean(user_description)
    domain = need.get("domain") or "generic"
    profile = source_profile or domain or "generic"

    if profile == "technology_gpu" or domain == "technology_gpu":
        return "technology_gpu:gpu_vram_catalog"

    if profile == "technology_ram" or domain == "technology_ram":
        generation = "ddr"
        for token in ["ddr2", "ddr3", "ddr4", "ddr5"]:
            if token in t:
                generation = token
                break
        form = "desktop" if any(x in t for x in ["desktop", "udimm", "dimm", "no sodimm", "niente sodimm"]) else "generic"
        return f"technology_ram:ram_{generation}_{form}"

    if profile == "technology_monitor" or domain == "technology_monitor":
        return "technology_monitor:monitor_specs_catalog"

    if profile == "technology_ssd" or domain == "technology_ssd":
        return "technology_ssd:ssd_specs_catalog"

    if profile == "tools" or any(x in t for x in ["trapano", "avvitatore", "smerigliatrice", "utensile"]):
        return "tools:cordless_tools_catalog"

    # Generic fallback: strip numbers, prices and threshold words so parameter changes
    # do not create a completely new cache when the subject is the same.
    stripped = re.sub(r"\b(?:almeno|minimo|oltre|sopra|superiore|budget|massimo|max|prezzo|euro|eur|€|gb|tb|mhz|hz|v|volt|w|watt|cm|mm|kg)\b", " ", t)
    stripped = re.sub(r"\d+(?:[.,]\d+)?", " ", stripped)
    words = [w for w in re.findall(r"[a-z0-9àèéìòù]+", stripped) if len(w) >= 3]
    return f"{profile}:" + "_".join(words[:8] or ["generic"])


def load_cache(key: str) -> dict | None:
    path = cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if data.get("schema_version") != CACHE_SCHEMA_VERSION:
        return None

    created = float(data.get("created_at", 0) or 0)
    if created and (time.time() - created) > CACHE_TTL_DAYS * 86400:
        return None
    return data


def save_cache(key: str, data: dict) -> None:
    path = cache_path(key)
    payload = dict(data)
    payload["schema_version"] = CACHE_SCHEMA_VERSION
    payload["created_at"] = payload.get("created_at") or time.time()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def detect_enrichment_need(user_description: str) -> dict:
    t = clean(user_description)
    out = {
        "domain": "generic",
        "needs_web": False,
        "reason": "",
        "min_vram_gb": None,
        "vehicle_terms": {},
    }

    if any(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", t) for term in ["ram", "ddr", "sodimm", "rdimm", "udimm"]) or "memoria" in t:
        out["domain"] = "technology_ram"
        out["needs_web"] = False
        out["reason"] = "RAM/memoria: le euristiche locali bastano di solito; web solo se servono compatibilità o modelli specifici."
        if any(x in t for x in ["compatibile", "compatibilità", "modello specifico", "lista qvl", "scheda madre"]):
            out["needs_web"] = True
            out["reason"] = "RAM/memoria con compatibilità o modello specifico: può essere utile cercare fonti tecniche."
        return out

    if ("scheda video" in t or "gpu" in t or "vga" in t) and "vram" in t:
        out["domain"] = "technology_gpu"
        out["needs_web"] = True
        out["reason"] = "GPU/VRAM: può essere utile conoscere tagli e modelli con memoria uguale o superiore."
        m = re.search(r"(?:minimo|almeno|>=|non meno di)\s*(\d+)\s*gb", t)
        if m:
            out["min_vram_gb"] = int(m.group(1))
        elif "24gb" in t.replace(" ", ""):
            out["min_vram_gb"] = 24
        return out

    tire_terms = ["gomme", "pneumatici", "ruote", "cerchi"]
    vehicle_terms = ["auto", "macchina", "yaris", "punto", "fiesta", "golf", "polo", "clio", "panda", "sport"]
    if any(x in t for x in tire_terms) and any(x in t for x in vehicle_terms):
        out["domain"] = "vehicle_tires"
        out["needs_web"] = True
        out["reason"] = "Gomme/auto: può servire cercare misure compatibili per modello/anno/allestimento."
        year = re.search(r"\b(19\d{2}|20\d{2})\b", t)
        if year:
            out["vehicle_terms"]["year"] = year.group(1)
        # Tiny extractor, intentionally conservative.
        for brand in ["toyota", "ford", "fiat", "volkswagen", "vw", "renault", "peugeot", "citroen", "opel", "honda", "nissan"]:
            if brand in t:
                out["vehicle_terms"]["brand"] = brand
        for model in ["yaris", "punto", "fiesta", "golf", "polo", "clio", "panda", "corsa", "civic", "micra"]:
            if model in t:
                out["vehicle_terms"]["model"] = model
        if "sport" in t:
            out["vehicle_terms"]["trim"] = "sport"
        return out

    dynamic_profile = detect_source_profile(user_description, out)
    if dynamic_profile not in {"generic", "technology_generic"}:
        profile_data = get_source_profile(dynamic_profile, user_description)
        out["domain"] = dynamic_profile
        out["needs_web"] = True
        out["reason"] = (
            "Categoria riconosciuta o profilo fonti dinamico: può essere utile cercare fonti specifiche "
            f"per {profile_data.get('label', dynamic_profile)}."
        )
        return out

    if any(x in t for x in ["compatibile", "compatibilità", "misura", "modello", "ricambio", "almeno", "minimo"]):
        out["domain"] = "generic_specs"
        out["needs_web"] = True
        out["reason"] = "Richiesta con compatibilità/specifiche: il web può aiutare a non inventare dettagli tecnici."
        return out

    return out


def heuristic_facts(user_description: str, need: dict) -> list[str]:
    facts: list[str] = []
    domain = need.get("domain")

    profile = detect_source_profile(user_description, need)
    for note in trusted_source_notes(profile, user_description):
        if note not in facts:
            facts.append(note)

    if domain == "technology_gpu":
        min_vram = need.get("min_vram_gb") or 24
        sizes = [min_vram] + [s for s in [32, 48, 64, 80] if s > min_vram]
        facts.append(
            "Per GPU con richiesta 'almeno/minimo N GB VRAM', cercare anche tagli superiori: "
            + ", ".join(f"{s}GB" for s in sizes)
            + "."
        )
        if min_vram <= 24:
            facts.append(
                "Esempi di keyword utili per 24GB+ VRAM: gpu 24gb, scheda video 24gb, vram 24gb, rtx 3090, rtx 4090, quadro 24gb, rtx a5000, rtx a6000."
            )
        facts.append(
            "Non usare il budget come keyword di ricerca; il budget va nei filtri numerici."
        )

    elif domain == "vehicle_tires":
        facts.append(
            "Per gomme/pneumatici auto, cercare misure compatibili per marca, modello, anno e allestimento; non inventare misure se la fonte non è chiara."
        )
        facts.append(
            "Le misure gomme possono variare per cerchio/allestimento/libretto: usare il risultato web come hint e tenere la compatibilità come nota da verificare."
        )

    elif domain == "generic_specs":
        facts.append(
            "Quando la richiesta dipende da compatibilità o specifiche tecniche, usare il web come appunto tecnico ma non come hard reject assoluto se le fonti sono incerte."
        )


    # Generic numeric threshold hints: "almeno 18v" means include compatible higher variants.
    for m in re.finditer(r"(?:almeno|minimo|>=|non meno di|da almeno|oltre|sopra|superiore a|più di|piu di)\s*(\d+(?:[.,]\d+)?)\s*(v|volt|ah|mah|w|watt|hz|kg|l|litri|mm|cm|gb|tb)\b", clean(user_description)):
        value = m.group(1).replace(",", ".")
        unit = m.group(2)
        facts.append(
            f"Richiesta con soglia minima {value}{unit}: includere anche varianti superiori compatibili quando hanno senso per la categoria, senza inventare incompatibilità."
        )

    return facts


def extract_threshold_rules(user_description: str) -> list[dict]:
    t = clean(user_description)
    patterns = [
        r"(?:almeno|minimo|>=|non meno di|da almeno|oltre|sopra|superiore a|piu di|più di)\s*(\d+(?:[.,]\d+)?)\s*(v|volt|ah|mah|w|watt|hz|kg|l|litri|mm|cm|gb|tb)\b",
        r"(\d+(?:[.,]\d+)?)\s*(v|volt|ah|mah|w|watt|hz|kg|l|litri|mm|cm|gb|tb)\s*(?:o più|o piu|in su|minimo|almeno|e oltre|o superiore)\b",
    ]
    rules = []
    seen = set()
    for pattern in patterns:
        for m in re.finditer(pattern, t):
            try:
                value = float(m.group(1).replace(",", "."))
            except Exception:
                continue
            unit = clean(m.group(2))
            if unit == "volt":
                unit = "v"
            if unit == "watt":
                unit = "w"
            if unit == "litri":
                unit = "l"
            key = (value, unit)
            if key in seen:
                continue
            seen.add(key)
            rules.append({"min_value": value, "unit": unit})
    return rules


def extract_values_with_unit(text: str, unit: str) -> list[float]:
    t = clean(text)
    aliases = {
        "v": ["v", "volt"],
        "w": ["w", "watt"],
        "l": ["l", "litri", "litro"],
    }.get(unit, [unit])

    values = []
    for alias in aliases:
        # Examples: 18v, 18 v, 18 volt, batteria 18V
        pattern = rf"(?<![a-z0-9])(\d+(?:[.,]\d+)?)\s*{re.escape(alias)}(?![a-z0-9])"
        for m in re.finditer(pattern, t):
            try:
                values.append(float(m.group(1).replace(",", ".")))
            except Exception:
                pass
    return values


def post_filter_web_results_by_threshold(
    results: list[dict],
    user_description: str,
    max_results: int = 5,
) -> tuple[list[dict], dict]:
    """
    Broad search -> post filter.

    If a minimum threshold is present, prefer results whose title/snippet/url explicitly
    mention a value >= threshold. Results with only lower explicit values are dropped.
    Results without any value are kept as fallback/source discovery only if there are
    not enough explicit matches.
    """
    rules = extract_threshold_rules(user_description)
    if not rules:
        return results[:max_results], {"mode": "no_threshold", "rules": [], "kept": min(len(results), max_results), "discarded": 0}

    explicit_ok = []
    unknown = []
    discarded = []
    for result in results:
        text = " ".join(str(result.get(k) or "") for k in ["title", "snippet", "url"])
        rule_statuses = []
        any_values = False
        all_ok = True

        for rule in rules:
            values = extract_values_with_unit(text, rule["unit"])
            if values:
                any_values = True
                best = max(values)
                ok = best >= float(rule["min_value"])
                rule_statuses.append({"rule": rule, "values": values, "best": best, "ok": ok})
                if not ok:
                    all_ok = False
            else:
                rule_statuses.append({"rule": rule, "values": [], "best": None, "ok": None})

        enriched = dict(result)
        enriched["threshold_filter"] = {
            "status": "match" if any_values and all_ok else ("below_minimum" if any_values else "unknown"),
            "rules": rule_statuses,
        }

        if any_values and all_ok:
            explicit_ok.append(enriched)
        elif any_values:
            discarded.append(enriched)
        else:
            unknown.append(enriched)

    kept = explicit_ok[:max_results]
    if len(kept) < max_results:
        kept.extend(unknown[: max_results - len(kept)])

    stats = {
        "mode": "threshold_post_filter",
        "rules": rules,
        "explicit_matches": len(explicit_ok),
        "unknown_kept": max(0, len(kept) - len(explicit_ok[:max_results])),
        "discarded_below_minimum": len(discarded),
        "raw_results": len(results),
        "kept": len(kept),
    }
    return kept, stats




def build_search_queries(user_description: str, need: dict, discover_sources: bool = True) -> list[str]:
    """
    Source-first query plan:
    1. Known trusted domains for the detected category.
    2. Domain-specific generic queries.
    3. Optional source-discovery queries if the category is unknown or known sources are not enough.
    """
    t = clean(user_description)
    domain = need.get("domain")
    queries: list[str] = []

    # First: targeted source registry.
    queries.extend(trusted_source_queries(user_description, need, max_queries=5))

    # Then: existing domain-specific general searches.
    if domain == "technology_gpu":
        # Broad search; VRAM threshold is applied by post_filter_web_results_by_threshold.
        queries.append("GPU VRAM models")
        queries.append("schede video VRAM modelli")
        queries.append("NVIDIA AMD GPU VRAM specifications")
    elif domain == "vehicle_tires":
        terms = need.get("vehicle_terms") or {}
        brand = terms.get("brand", "")
        model = terms.get("model", "")
        year = terms.get("year", "")
        trim = terms.get("trim", "")
        base = " ".join(x for x in [brand, model, year, trim] if x).strip()
        if not base:
            base = user_description
        queries.append(f"{base} tire size")
        queries.append(f"{base} tyre size")
        queries.append(f"{base} misura pneumatici")
    elif domain == "generic_specs":
        queries.append(f"{user_description} specifiche compatibilità")
        queries.append(f"{user_description} modelli compatibili")
    elif extract_threshold_rules(user_description):
        # Broad query; threshold is applied after fetching results.
        queries.append(f"{user_description} specifiche")
    elif not queries:
        queries.append(f"{user_description} specifiche")

    if discover_sources:
        queries.extend(source_discovery_queries(user_description, need, max_queries=2))

    # Deduplicate preserving order.
    out = []
    seen = set()
    for q in queries:
        q = re.sub(r"\s+", " ", str(q)).strip()
        key = q.lower()
        if q and key not in seen:
            seen.add(key)
            out.append(q)
        if len(out) >= 8:
            break
    return out


def strip_html(value: str) -> str:
    s = re.sub(r"<script.*?</script>", " ", value, flags=re.I | re.S)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def decode_duckduckgo_href(href: str) -> str:
    href = html.unescape(str(href or "")).strip()
    if not href:
        return ""

    parsed = urllib.parse.urlparse(href)
    qs = urllib.parse.parse_qs(parsed.query)
    if "uddg" in qs and qs["uddg"]:
        return qs["uddg"][0]

    if href.startswith("//"):
        return "https:" + href

    return href


def normalize_search_url(url: str) -> str:
    url = decode_duckduckgo_href(url)
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    blocked = ["duckduckgo.com", "google.com", "bing.com", "yahoo.com"]
    if any(host == b or host.endswith("." + b) for b in blocked):
        return ""

    if not parsed.scheme.startswith("http"):
        return ""

    return url


def normalize_search_result(item: dict) -> dict | None:
    title = str(item.get("title") or item.get("heading") or "").strip()
    url = str(item.get("href") or item.get("url") or item.get("link") or "").strip()
    snippet = str(item.get("body") or item.get("snippet") or item.get("description") or "").strip()

    url = normalize_search_url(url)
    title = strip_html(title)
    snippet = strip_html(snippet)

    if not title or not url:
        return None

    return {
        "title": title[:180],
        "url": url[:500],
        "snippet": snippet[:300],
    }


def try_ddgs_backend(query: str, max_results: int = 5, timeout: float = DEFAULT_TIMEOUT) -> tuple[list[dict], dict]:
    """
    Optional dependency backend.

    Preferred package: ddgs
    Legacy fallback: duckduckgo_search
    """
    wanted = os.environ.get("SPYENGINE_SEARCH_BACKEND", "auto").strip().lower()
    if wanted in {"stdlib", "html", "manual"}:
        return [], {"backend": "ddgs", "skipped": f"disabled by SPYENGINE_SEARCH_BACKEND={wanted}"}

    DDGS = None
    package = None
    import_errors = []

    try:
        from ddgs import DDGS as _DDGS  # type: ignore
        DDGS = _DDGS
        package = "ddgs"
    except Exception as e:
        import_errors.append(f"ddgs: {e}")

    if DDGS is None:
        try:
            from duckduckgo_search import DDGS as _DDGS  # type: ignore
            DDGS = _DDGS
            package = "duckduckgo_search"
        except Exception as e:
            import_errors.append(f"duckduckgo_search: {e}")

    if DDGS is None:
        return [], {
            "backend": "ddgs",
            "available": False,
            "import_errors": import_errors,
            "hint": "pip install -U ddgs",
        }

    region = os.environ.get("SPYENGINE_DDGS_REGION", "it-it")
    safesearch = os.environ.get("SPYENGINE_DDGS_SAFESEARCH", "moderate")
    ddgs_backend = os.environ.get("SPYENGINE_DDGS_BACKEND", "auto")

    try:
        with DDGS(timeout=int(timeout)) as ddgs:
            raw = ddgs.text(
                query,
                region=region,
                safesearch=safesearch,
                backend=ddgs_backend,
                max_results=max_results,
            )

            results = []
            for item in raw or []:
                if not isinstance(item, dict):
                    continue
                norm = normalize_search_result(item)
                if norm:
                    norm["search_backend"] = package
                    results.append(norm)
                if len(results) >= max_results:
                    break

            return results, {
                "backend": package,
                "available": True,
                "region": region,
                "ddgs_backend": ddgs_backend,
                "result_count": len(results),
            }
    except Exception as e:
        return [], {
            "backend": package,
            "available": True,
            "error": str(e),
            "region": region,
            "ddgs_backend": ddgs_backend,
        }


def extract_duckduckgo_results(text: str, max_results: int = 5) -> list[dict]:
    text = str(text or "")
    results: list[dict] = []
    seen = set()

    def add(title: str, href: str, snippet: str = ""):
        item = normalize_search_result({"title": title, "href": href, "body": snippet})
        if not item:
            return
        marker = clean(item.get("url") or item.get("title"))
        if marker in seen:
            return
        seen.add(marker)
        item["search_backend"] = "stdlib_html"
        results.append(item)

    for m in re.finditer(r'<a\b([^>]*class="[^"]*result__a[^"]*"[^>]*)>(.*?)</a>', text, flags=re.I | re.S):
        attrs = m.group(1)
        title = m.group(2)
        hm = re.search(r'href="([^"]+)"', attrs, flags=re.I)
        if hm:
            add(title, hm.group(1))
        if len(results) >= max_results:
            return results[:max_results]

    for m in re.finditer(r'<a\b([^>]*class="[^"]*result-link[^"]*"[^>]*)>(.*?)</a>', text, flags=re.I | re.S):
        attrs = m.group(1)
        title = m.group(2)
        hm = re.search(r'href="([^"]+)"', attrs, flags=re.I)
        if hm:
            add(title, hm.group(1))
        if len(results) >= max_results:
            return results[:max_results]

    for m in re.finditer(r'<a\b([^>]*)>(.*?)</a>', text, flags=re.I | re.S):
        attrs = m.group(1)
        title = strip_html(m.group(2))
        if len(title) < 4:
            continue
        hm = re.search(r'href="([^"]+)"', attrs, flags=re.I)
        if not hm:
            continue
        add(title, hm.group(1))
        if len(results) >= max_results:
            return results[:max_results]

    return results[:max_results]


def detect_search_block_reason(text: str) -> str:
    low = clean(text)
    if not low:
        return "empty_response"
    if "captcha" in low or "unusual traffic" in low or "bot" in low:
        return "possible_antibot_or_captcha"
    if "no results" in low or "nessun risultato" in low:
        return "search_engine_no_results"
    if len(text) < 1000:
        return "short_response"
    return "parser_no_matches"


def fetch_search_endpoint(url: str, timeout: float) -> tuple[str, dict]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": os.environ.get(
                "SPYENGINE_WEB_USER_AGENT",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(800_000)
        status = getattr(resp, "status", None) or resp.getcode()

    text = raw.decode("utf-8", errors="replace")
    return text, {"status": status, "bytes": len(raw), "reason": detect_search_block_reason(text)}


def search_stdlib_html_with_diagnostics(query: str, max_results: int = 5, timeout: float = DEFAULT_TIMEOUT) -> tuple[list[dict], dict]:
    endpoints = [
        ("ddg_html", "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})),
        ("ddg_lite", "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query})),
        ("ddg_legacy", "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})),
    ]

    diagnostics = {"backend": "stdlib_html", "query": query, "endpoints": []}
    best_results: list[dict] = []

    for name, url in endpoints:
        try:
            text, info = fetch_search_endpoint(url, timeout=timeout)
            results = extract_duckduckgo_results(text, max_results=max_results)
            info.update({"endpoint": name, "result_count": len(results), "url": url})
            diagnostics["endpoints"].append(info)
            if results:
                diagnostics["selected_endpoint"] = name
                return results, diagnostics
            best_results = results
        except Exception as e:
            diagnostics["endpoints"].append({"endpoint": name, "error": str(e), "url": url})

    diagnostics["selected_endpoint"] = None
    return best_results, diagnostics


def search_web_with_diagnostics(query: str, max_results: int = 5, timeout: float = DEFAULT_TIMEOUT) -> tuple[list[dict], dict]:
    """
    Search order:
    1. Optional ddgs / duckduckgo_search package if installed.
    2. Stdlib DuckDuckGo HTML/Lite parser fallback.
    """
    diagnostics = {"query": query, "attempts": []}

    results, ddgs_diag = try_ddgs_backend(query, max_results=max_results, timeout=timeout)
    diagnostics["attempts"].append(ddgs_diag)
    if results:
        diagnostics["selected_backend"] = ddgs_diag.get("backend")
        return results, diagnostics

    results, html_diag = search_stdlib_html_with_diagnostics(query, max_results=max_results, timeout=timeout)
    diagnostics["attempts"].append(html_diag)
    diagnostics["selected_backend"] = html_diag.get("backend") if results else None
    return results, diagnostics


def search_duckduckgo_html(query: str, max_results: int = 5, timeout: float = DEFAULT_TIMEOUT) -> list[dict]:
    results, _diag = search_web_with_diagnostics(query, max_results=max_results, timeout=timeout)
    return results


def enrich_user_description(
    user_description: str,
    use_web: bool = False,
    refresh: bool = False,
    max_results: int = 5,
    progress: Any = None,
    force_web: bool = False,
) -> dict:
    def emit(stage: str, message: str, detail: Any = None):
        if not progress:
            return
        try:
            progress(stage, message, detail)
        except Exception:
            pass

    need = detect_enrichment_need(user_description)
    facts = heuristic_facts(user_description, need)
    source_profile = detect_source_profile(user_description, need)
    learned_profile = learn_profile_from_description(source_profile, user_description)
    source_domains = trusted_source_domains(source_profile, user_description)

    prompt_results = max(1, int(max_results or KNOWLEDGE_PROMPT_RESULTS))
    per_query_results = KNOWLEDGE_PER_QUERY_RESULTS
    collect_target = max(prompt_results, KNOWLEDGE_COLLECT_RESULTS)
    filtered_target = max(prompt_results, min(KNOWLEDGE_FILTERED_TARGET, collect_target))
    subject_key = canonical_knowledge_subject(user_description, need, source_profile)

    should_build_queries = bool(need.get("needs_web") or force_web)
    if force_web and not need.get("needs_web"):
        emit(
            "web_force",
            "Refresh web richiesto: genero query anche se le euristiche locali sembrano sufficienti",
            {"domain": need.get("domain"), "source_profile": source_profile},
        )

    queries = build_search_queries(user_description, need, discover_sources=True) if should_build_queries else []

    if learned_profile:
        emit(
            "source_profile_memory",
            f"Profilo fonti aggiornato: {source_profile}",
            {
                "source_profile": source_profile,
                "match_terms": learned_profile.get("match_terms", [])[:20],
                "seen_count": learned_profile.get("seen_count"),
                "domains": learned_profile.get("domains", [])[:12],
            },
        )

    key = cache_key(json.dumps(
        {
            "schema": CACHE_SCHEMA_VERSION,
            "subject": subject_key,
            "source_profile": source_profile,
        },
        ensure_ascii=False,
    ))
    cached = None if refresh else load_cache(key)
    if cached:
        raw_cached = cached.get("web_results_all") or cached.get("web_results") or []
        refiltered, refilter_stats = post_filter_web_results_by_threshold(
            raw_cached,
            user_description,
            max_results=prompt_results,
        )
        emit(
            "cache_hit",
            f"Cache knowledge soggetto trovata: {key}",
            {
                "cache_key": key,
                "cache_subject": subject_key,
                "source_profile": cached.get("source_profile"),
                "queries": cached.get("queries", []),
                "facts": cached.get("facts", []),
                "raw_results_count": len(raw_cached),
                "filtered_results_count": len(refiltered),
                "post_filter": refilter_stats,
            },
        )
        if refilter_stats.get("mode") == "threshold_post_filter":
            emit(
                "post_filter",
                (
                    f"Filtro soglia da cache: {refilter_stats.get('explicit_matches', 0)} match espliciti, "
                    f"{refilter_stats.get('discarded_below_minimum', 0)} sotto soglia"
                ),
                refilter_stats,
            )
        out = dict(cached)
        out.update(
            {
                "need": need,
                "web_results": refiltered,
                "post_filter": refilter_stats,
                "cache_key": key,
                "cache_subject": subject_key,
                "from_cache": True,
            }
        )
        return out

    if refresh:
        emit(
            "cache_refresh",
            f"Refresh richiesto: ignoro cache {key}",
            {
                "force_web": bool(force_web),
                "queries_count": len(queries),
                "needs_web": bool(need.get("needs_web")),
                "cache_subject": subject_key,
            },
        )
    else:
        emit("cache_miss", f"Nessuna cache knowledge valida: {key}", {"cache_subject": subject_key})

    web_results: list[dict] = []
    errors: list[str] = []

    if use_web and queries:
        emit(
            "web_plan",
            f"Ricerca source-first: {len(queries)} query, target raccolta {collect_target}",
            {
                "source_profile": source_profile,
                "source_domains": source_domains,
                "queries": queries,
                "force_web": bool(force_web),
                "cache_subject": subject_key,
                "per_query_results": per_query_results,
                "collect_target": collect_target,
                "filtered_target": filtered_target,
                "prompt_results": prompt_results,
            },
        )
        for query in queries:
            try:
                emit("web_search", query)
                found, diag = search_web_with_diagnostics(query, max_results=per_query_results, timeout=DEFAULT_TIMEOUT)
                if found:
                    emit("web_result", f"{len(found)} risultati", found[:3])
                else:
                    emit("web_result", "0 risultati", diag)
                web_results.extend(found)
                # If there is a threshold (e.g. >=24GB VRAM, >=18V), do not stop on raw results.
                # Stop only when post-filter has enough explicit matches.
                threshold_rules = extract_threshold_rules(user_description)
                if len(web_results) >= collect_target:
                    if threshold_rules:
                        preview_filtered, preview_stats = post_filter_web_results_by_threshold(
                            web_results,
                            user_description,
                            max_results=filtered_target,
                        )
                        explicit = int(preview_stats.get("explicit_matches") or 0)
                        if explicit >= filtered_target:
                            emit(
                                "web_enough",
                                f"Raggiunti {explicit} match espliciti dopo filtro su {len(web_results)} grezzi",
                                preview_stats,
                            )
                            break
                        emit(
                            "web_continue",
                            (
                                f"{len(web_results)} risultati grezzi raccolti, ma solo {explicit} match espliciti; "
                                "continuo a costruire il database del soggetto"
                            ),
                            preview_stats,
                        )
                    else:
                        emit("web_enough", f"Raggiunto target raccolta: {len(web_results)} risultati grezzi")
                        break
            except Exception as e:
                msg = f"{query}: {e}"
                errors.append(msg)
                emit("web_error", msg)
    elif use_web and not queries:
        reason = "Nessuna query utile generata"
        if not need.get("needs_web") and not force_web:
            reason = "Web non necessario per questo dominio: euristiche locali sufficienti"
        emit(
            "web_skip",
            reason,
            {
                "domain": need.get("domain"),
                "source_profile": source_profile,
                "needs_web": bool(need.get("needs_web")),
                "force_web": bool(force_web),
                "queries_count": len(queries),
            },
        )
    else:
        emit("web_skip", "Web disattivato: uso solo euristiche/cache")

    # Deduplicate URLs/titles first, without cutting too early:
    # broad search may need post-filtering before final max_results.
    unique_results = []
    seen = set()
    for r in web_results:
        marker = clean(r.get("url") or r.get("title"))
        if not marker or marker in seen:
            continue
        seen.add(marker)
        unique_results.append(r)

    deduped, post_filter_stats = post_filter_web_results_by_threshold(
        unique_results,
        user_description,
        max_results=prompt_results,
    )
    if post_filter_stats.get("mode") == "threshold_post_filter":
        emit(
            "post_filter",
            (
                f"Filtro soglia: {post_filter_stats.get('explicit_matches', 0)} match espliciti, "
                f"{post_filter_stats.get('discarded_below_minimum', 0)} sotto soglia"
            ),
            post_filter_stats,
        )

    learned_domains = []
    if deduped:
        learned_domains = learn_sources_from_results(source_profile, user_description, deduped)
        if learned_domains:
            emit("source_profile_learned", f"Fonti apprese per {source_profile}: {', '.join(learned_domains[:5])}", learned_domains)
            source_domains = trusted_source_domains(source_profile, user_description)

    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "need": need,
        "source_profile": source_profile,
        "source_domains": source_domains,
        "cache_subject": subject_key,
        "collection": {
            "prompt_results": prompt_results,
            "per_query_results": per_query_results,
            "collect_target": collect_target,
            "filtered_target": filtered_target,
            "raw_results_count": len(unique_results),
            "cached_results_cap": KNOWLEDGE_CACHE_RESULT_CAP,
        },
        "force_web": bool(force_web),
        "should_build_queries": bool(should_build_queries),
        "learned_domains": learned_domains,
        "profile_memory": {
            "match_terms": (learned_profile or {}).get("match_terms", [])[:20],
            "seen_count": (learned_profile or {}).get("seen_count"),
        },
        "queries": queries,
        "facts": facts,
        "web_results": deduped,
        "web_results_all": unique_results[:KNOWLEDGE_CACHE_RESULT_CAP],
        "post_filter": post_filter_stats,
        "errors": errors,
        "from_cache": False,
    }

    if facts or deduped:
        save_cache(key, payload)
        emit(
            "cache_save",
            f"Salvati appunti knowledge in cache: {key}",
            {
                "facts_count": len(facts),
                "web_results_count": len(deduped),
                "raw_results_count": len(unique_results),
                "cache_key": key,
                "cache_subject": subject_key,
            },
        )
    else:
        emit("cache_skip_save", "Nessun appunto utile da salvare")

    payload["cache_key"] = key
    return payload


def format_enrichment_for_prompt(enrichment: dict) -> str:
    if not enrichment:
        return ""

    lines: list[str] = []
    need = enrichment.get("need") or {}
    domain = need.get("domain", "generic")
    reason = need.get("reason", "")

    lines.append("Contesto tecnico opzionale per compilare la config.")
    lines.append("Usalo solo come hint: non copiare fonti/URL nella item_description, non inventare se incerto.")
    lines.append(f"Dominio stimato: {domain}.")
    source_profile = enrichment.get("source_profile")
    source_domains = enrichment.get("source_domains") or []
    collection = enrichment.get("collection") or {}
    if collection:
        lines.append(
            "Database knowledge locale: "
            f"{collection.get('raw_results_count', 0)} risultati grezzi nel soggetto, "
            f"{collection.get('prompt_results', '?')} risultati filtrati passati al prompt."
        )
    if source_profile:
        profile_data = get_source_profile(source_profile, "")
        label = profile_data.get("label", source_profile)
        lines.append(f"Profilo fonti: {source_profile} ({label}).")
    if source_domains:
        lines.append("Fonti preferite per questa categoria: " + ", ".join(source_domains[:8]) + ".")
    memory = enrichment.get("profile_memory") or {}
    if memory.get("match_terms"):
        lines.append("Termini profilo appresi: " + ", ".join(memory.get("match_terms", [])[:12]) + ".")
    if reason:
        lines.append(f"Perché: {reason}")

    queries = enrichment.get("queries") or []
    if queries:
        lines.append("Piano ricerca source-first:")
        for query in queries[:8]:
            lines.append(f"- {query}")

    facts = enrichment.get("facts") or []
    if facts:
        lines.append("Appunti euristici:")
        for fact in facts[:8]:
            lines.append(f"- {fact}")

    post_filter = enrichment.get("post_filter") or {}
    if post_filter.get("mode") == "threshold_post_filter":
        lines.append(
            "Filtro post-ricerca: soglia minima applicata dopo ricerca larga; "
            f"match espliciti={post_filter.get('explicit_matches', 0)}, "
            f"sotto soglia scartati={post_filter.get('discarded_below_minimum', 0)}, "
            f"incerti tenuti={post_filter.get('unknown_kept', 0)}."
        )

    results = enrichment.get("web_results") or []
    if results:
        lines.append("Risultati web sintetici:")
        for r in results[:6]:
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            url = r.get("url", "")
            one = f"- {title}"
            if snippet:
                one += f": {snippet}"
            if url:
                one += f" [{url}]"
            lines.append(one[:900])

    errors = enrichment.get("errors") or []
    if errors and not results:
        lines.append("Nota: ricerca web non riuscita; usa solo euristiche locali.")

    return "\n".join(lines).strip()
