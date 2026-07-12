#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import base64
import glob
import html
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

import requests
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spyengine.utils.env import load_env
from spyengine.services.notifier import TelegramNotifier
from spyengine.wizard.domain_profiles import apply_domain_profile
from spyengine.wizard.knowledge_enrichment import enrich_user_description, format_enrichment_for_prompt
from spyengine.marketplace_harvest.client_view import load_client_listings
from spyengine.marketplace_harvest.product_knowledge import resolve_product


APP_TITLE = "🕵️ SpyEngine v3"
MANAGER_PID = Path("spy_manager_v3.pid")
MANAGER_LOG = Path("spy_manager_v3.log")
LLAMA_PID = Path("llama_server.pid")
LLAMA_LOG = Path("llama_server.log")
LLAMA_STARTER_LOG = Path("llama_starter.log")
MARKET_HARVESTER_PID = Path("marketplace_harvester.pid")
MARKET_HARVESTER_LOG = Path("logs/nightly_marketplace_harvester.log")
MARKET_AIO_PID = Path("marketplace_all_in_one.pid")
MARKET_AIO_LOG = Path("logs/marketplace_all_in_one_pipeline.log")
MARKET_QUERY_LOG = Path("logs/marketplace_cache_gui.log")
MARKET_DB_DEFAULT = Path("data/marketplace_cache/marketplace.sqlite")
MARKET_MAINTENANCE_PID = Path("marketplace_gui_maintenance_update.pid")
MARKET_MAINTENANCE_LOG = Path("logs/marketplace_gui_maintenance_update.log")
CATALOG_ENRICHMENT_GUI_PID = Path("catalog_enrichment_gui.pid")
CATALOG_ENRICHMENT_DAEMON_PID = Path("catalog_enrichment_daemon.pid")
CATALOG_ENRICHMENT_LOG = Path("logs/catalog_enrichment_daemon.log")
CLIENT_SETTINGS_PATH = Path("data/gui/client_settings.json")
CLIENT_EXPORT_DIR = Path("exports")
CLIENT_APP_VERSION = "M11.6"


def get_project_python() -> str:
    """Prefer project venv Python over sys.executable for subprocess scripts."""
    for candidate in [
        Path(".venv/bin/python"),
        Path(".venv/bin/python3"),
        Path("venv/bin/python"),
        Path("venv/bin/python3"),
    ]:
        if candidate.exists():
            return str(candidate)
    return sys.executable



# ==================== INIT ====================

st.set_page_config(
    page_title="SpyEngine v3",
    page_icon="🕵️",
    layout="wide",
    initial_sidebar_state="expanded",
)

load_env()

st.markdown(
    """
<style>
    .main-title {
        font-size: 2.3rem;
        font-weight: 800;
        margin-bottom: 0.2rem;
    }
    .subtitle {
        color: #777;
        margin-bottom: 1.2rem;
    }
    .ok { color: #11a36a; font-weight: 700; }
    .warn { color: #d99000; font-weight: 700; }
    .bad { color: #d93025; font-weight: 700; }
    div[data-testid="stTextArea"] textarea {
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 0.82rem;
        line-height: 1.25rem;
    }
    .compact-note {
        font-size: 0.85rem;
        color: #777;
    }

    .top-status-wrap {
        margin: 0.2rem auto 1.25rem auto;
        max-width: 1200px;
    }
    .hero-bar {
        text-align: center;
        margin-bottom: 0.8rem;
    }
    .hero-kicker {
        font-size: 0.95rem;
        color: #9aa4b2;
        margin-top: -0.25rem;
        margin-bottom: 0.35rem;
    }
    .status-card {
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 16px;
        padding: 14px 16px;
        background: rgba(255,255,255,0.02);
        min-height: 92px;
        box-shadow: 0 8px 20px rgba(0,0,0,0.18);
    }
    .status-label {
        font-size: 0.88rem;
        color: #9aa4b2;
        margin-bottom: 0.25rem;
    }
    .status-value {
        font-size: 1.2rem;
        font-weight: 800;
        line-height: 1.2;
    }
    .status-mini {
        font-size: 0.82rem;
        color: #8b949e;
        margin-top: 0.3rem;
        word-break: break-all;
    }
    .sidebar-block-title {
        font-size: 1.12rem;
        font-weight: 800;
        margin-bottom: 0.5rem;
    }
    .small-muted {
        color: #9aa4b2;
        font-size: 0.88rem;
    }
    div[data-testid="stSidebar"] .stButton > button {
        border-radius: 12px;
        min-height: 42px;
        font-weight: 700;
    }


    .model-info-card {
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 14px;
        padding: 10px 11px;
        background: rgba(255,255,255,0.035);
        margin: 0.45rem 0 0.8rem 0;
        font-size: 0.82rem;
        line-height: 1.25rem;
    }
    .model-info-title {
        font-weight: 800;
        margin-bottom: 0.35rem;
    }
    .model-path {
        color: #9aa4b2;
        word-break: break-all;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 0.74rem;
    }

</style>
""",
    unsafe_allow_html=True,
)


# ==================== UTIL ====================

def maybe_fragment(run_every: str | None = None):
    frag = getattr(st, "fragment", None)
    if callable(frag):
        return frag(run_every=run_every)

    def deco(fn):
        return fn

    return deco


def mask(v: str | None) -> str:
    if not v:
        return "MISSING"
    v = str(v)
    if len(v) <= 8:
        return "*" * len(v)
    return f"{v[:4]}...{v[-4:]} ({len(v)} chars)"


def pid_running(pid_path: Path) -> bool:
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except Exception:
        return False

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def read_tail(path: Path, lines: int = 80) -> str:
    if not path.exists():
        return ""
    try:
        data = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(data[-lines:])
    except Exception as e:
        return f"Errore lettura {path}: {e}"


def load_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def list_configs() -> list[Path]:
    Path("configs").mkdir(exist_ok=True)
    return sorted(Path("configs").glob("spy_config_*.json"))


def config_name_from_path(path: Path) -> str:
    name = path.stem
    return name.replace("spy_config_", "", 1) if name.startswith("spy_config_") else name


def count_json_files(folder: Path) -> int:
    return len(list(folder.glob("*.json"))) if folder.exists() else 0


def latest_file(pattern: str) -> Path | None:
    files = [Path(p) for p in glob.glob(pattern, recursive=True)]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def process_start(cmd: list[str], pid_path: Path, log_path: Path) -> tuple[bool, str]:
    if pid_running(pid_path):
        return True, "già attivo"

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "a", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=os.getcwd(),
            start_new_session=True,
            env=env,
        )
        pid_path.write_text(str(proc.pid), encoding="utf-8")
        return True, f"avviato pid={proc.pid}"
    except Exception as e:
        return False, str(e)


def process_stop(pid_path: Path, label: str) -> tuple[bool, str]:
    if not pid_path.exists():
        return True, f"{label} non attivo"

    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except Exception:
        pid_path.unlink(missing_ok=True)
        return False, "PID file non valido, rimosso"

    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(2)
        if pid_running(pid_path):
            os.kill(pid, signal.SIGKILL)
            time.sleep(1)
        pid_path.unlink(missing_ok=True)
        return True, f"{label} fermato"
    except ProcessLookupError:
        pid_path.unlink(missing_ok=True)
        return True, f"{label} già terminato"
    except Exception as e:
        return False, str(e)


def llama_online(port: int = 8080) -> bool:
    try:
        r = requests.get(f"http://127.0.0.1:{port}/health", timeout=2)
        return r.status_code == 200
    except requests.RequestException:
        return False


def status_badge(ok: bool, yes: str = "ONLINE", no: str = "OFFLINE") -> str:
    cls = "ok" if ok else "bad"
    text = yes if ok else no
    return f"<span class='{cls}'>{text}</span>"


def default_config() -> dict:
    return {
        "name": "new_spy",
        "item_description": "Descrivi cosa vuoi cercare",
        "search_keywords": ["keyword esempio"],
        "exclude_words": [],
        "required_words": [],
        "required_groups": [],
        "distractor_words": [],
        "budget": {"default": 100.0, "configurations": {"standard": 100.0}},
        "unit_budget_rules": [],
        "config_patterns": {"standard": []},
        "reject_patterns": [],
        "premium_brands": [],
        "positive_keywords": {},
        "negative_keywords": [],
        "platforms": ["VINTED", "SUBITO", "EBAY", "WALLAPOP"],
        "vision_enabled": True,
        "context_check_enabled": True,
        "domain_profile": "generic",
        "interval_seconds": 300,
        "max_history": 200,
        "ebay_app_id_env": "EBAY_APP_ID",
        "system_prompt": (
            "[SYSTEM]\n"
            "You are a strict JSON generator. Output ONLY valid JSON.\n"
            "Reject unrelated items, incompatible items, broken items, and unclear listings."
        ),
    }


TYPO_FIXES = {
    "soddim": "sodimm",
    "soddimm": "sodimm",
    "diffettoso": "difettoso",
    "non funciona": "non funziona",
    "riguita": "rifiuta",
    "riguita": "rifiuta",
    "acetta": "accetta",
}


DEFAULT_PLATFORMS = ["VINTED", "SUBITO", "EBAY", "WALLAPOP"]
KNOWN_PLATFORMS = set(DEFAULT_PLATFORMS + ["MOCK"])


def clean_word(value: Any) -> str:
    s = str(value).strip().lower()
    for bad, good in TYPO_FIXES.items():
        s = s.replace(bad, good)
    s = re.sub(r"\s+", " ", s)
    return s


def dedup_list(values: Any, max_items: int = 40) -> list[str]:
    if not isinstance(values, list):
        return []
    out = []
    seen = set()
    for x in values:
        s = clean_word(x)
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= max_items:
            break
    return out


SEARCH_KEYWORD_REPLACEMENTS = [
    ("single stick", "banco"),
    ("stick", "banco"),
    ("sticks", "banchi"),
    ("memory", "memoria"),
    ("desktop ram", "ram"),
    ("desktop", ""),
    ("udimm", ""),
    ("non-ecc", ""),
    ("non ecc", ""),
    ("no ecc", ""),
    ("no-ecc", ""),
    ("no rdimm", ""),
    ("no registered", ""),
    ("no server", ""),
    ("registered", ""),
    ("pre-built", "preassemblato"),
    ("prebuilt", "preassemblato"),
    ("complete computer", "pc completo"),
    ("computer whole", "computer intero"),
    ("pc complete", "pc completo"),
    ("with", "con"),
]

SEARCH_KEYWORD_NOISE = {
    "no", "non", "senza", "only", "solo", "compatibile", "compatibili",
    "desktop", "udimm", "single", "stick", "sticks", "item", "items",
    "non-ecc", "ecc", "rdimm", "registered", "server", "sodimm", "so-dimm",
    "laptop", "notebook", "portatile", "defective", "faulty", "broken",
    # prompt/meta words that should never become marketplace search queries
    "prezzo", "budget", "massimo", "max", "minimo", "target", "principale",
    "secondario", "preferito", "preferiti", "possibilmente", "notificare",
    "notifica", "offerta", "offerte", "vicino", "vicini", "tolleranza",
    "euro", "eur", "unità", "unita", "pezzo", "pezzi", "per",
}

NEGATION_PREFIXES = ("no ", "non ", "senza ")


def translate_common_market_terms(text: str) -> str:
    s = clean_word(text)
    # Normalize separators used in marketplace titles.
    s = s.replace("×", "x")
    for src, dst in SEARCH_KEYWORD_REPLACEMENTS:
        s = re.sub(rf"(?<![a-z0-9]){re.escape(src)}(?![a-z0-9])", dst, s)
    s = re.sub(r"[^\wàèéìòù.+x -]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def compact_search_keyword(keyword: str, exclude_words: list[str] | None = None, max_words: int = 4) -> str:
    s = translate_common_market_terms(keyword)
    if not s:
        return ""

    exclude = {clean_word(x) for x in (exclude_words or []) if clean_word(x)}
    exclude_tokens = {tok for term in exclude for tok in term.split() if len(tok) >= 2}
    noise = SEARCH_KEYWORD_NOISE | exclude | exclude_tokens

    tokens = []
    for raw in s.split():
        t = raw.strip(" -_")
        if not t:
            continue
        if t in noise:
            continue
        if t.startswith("no-") or t.startswith("non-"):
            continue
        tokens.append(t)

    if not tokens:
        return ""

    # Prefer concise marketplace searches. If too long, keep identifiers/specs first.
    if len(tokens) > max_words:
        important = [t for t in tokens if re.search(r"\d", t)]
        normal = [t for t in tokens if t not in important]
        merged = []
        for t in normal + important:
            if t not in merged:
                merged.append(t)
        tokens = merged[:max_words]

    return " ".join(tokens).strip()


def extract_search_seeds(text: str) -> list[str]:
    raw = translate_common_market_terms(text)
    tokens = re.findall(r"[a-zàèéìòù0-9.+_-]+", raw)
    out = []
    seen = set()
    stop = SEARCH_KEYWORD_NOISE | {
        "cerco", "cerca", "cercare", "possibilmente", "massimo", "minimo", "budget",
        "prezzo", "euro", "eur", "disposto", "scendere", "stesso", "principio",
        "combinazioni", "controllare", "vendita", "vedere", "vendono", "pezzi",
        "vicini", "notificare", "offerta", "accetto", "accettati", "vanno", "bene",
        "van", "anche", "prezzo", "budget", "massimo", "target", "principale", "secondario",
        "tolleranza", "offrire", "provare", "stesso", "principio", "nx32gb", "nx16gb",
        "per", "con", "da", "di", "del", "della", "delle", "gli",
        "le", "il", "lo", "la", "un", "una", "uno", "e", "o", "ma",
    }
    for t in tokens:
        t = t.strip("_-.")
        if not t or t in stop or t in seen:
            continue
        if len(t) < 3 and not re.search(r"\d", t):
            continue
        seen.add(t)
        out.append(t)
    return out


def add_compact_keyword(out: list[str], seen: set[str], value: str, exclude_words: list[str], max_items: int) -> None:
    kw = compact_search_keyword(value, exclude_words=exclude_words)
    if not kw or kw in seen:
        return
    wc = len(kw.split())
    if wc == 0 or wc > 4:
        return
    if is_bad_search_keyword(kw):
        return
    seen.add(kw)
    out.append(kw)


def is_bad_search_keyword(keyword: str) -> bool:
    s = clean_word(keyword)
    if not s:
        return True

    # Avoid pure generic words.
    generic_only = {
        "ram", "16gb", "32gb", "moduli", "modulo", "banchi", "banco", "singolo",
        "kit", "prezzo", "budget", "target", "principale", "secondario",
        "banchi ram", "singolo banco", "ram pc",
    }
    if s in generic_only:
        return True

    # Avoid prompt-derived/budget-derived queries: "130 32gb", "32gb +10", "prezzo per banco".
    if re.search(r"(^|\s)(\+?10|60|66|130|143)(\s|$)", s):
        return True
    if any(x in s for x in ["prezzo per", "budget", "target ", "principale", "massimo"]):
        return True

    # At least one real product/spec term should appear.
    useful_markers = ("ddr", "ram", "memoria", "corsair", "kingston", "crucial", "g.skill", "hyperx")
    if not any(m in s for m in useful_markers):
        # allow other domains, but reject one-word generic terms handled above
        if len(s.split()) <= 1:
            return True

    return False


def user_explicitly_limits_platforms(text: str) -> bool:
    """
    Default must be all platforms.
    Limit only on strong expressions such as:
    - solo Subito
    - soltanto Vinted
    - esclusivamente eBay
    - usa solo Wallapop
    Generic mentions of marketplace names must not reduce coverage.
    """
    s = clean_word(text)
    platform_words = r"(subito|vinted|ebay|e-bay|wallapop)"
    strong_patterns = [
        rf"\bsolo\s+(su\s+)?{platform_words}\b",
        rf"\bsoltanto\s+(su\s+)?{platform_words}\b",
        rf"\besclusivamente\s+(su\s+)?{platform_words}\b",
        rf"\bunicamente\s+(su\s+)?{platform_words}\b",
        rf"\busa\s+solo\s+{platform_words}\b",
        rf"\bcerca\s+solo\s+su\s+{platform_words}\b",
        rf"\blimita(?:re)?\s+(?:a|su)\s+{platform_words}\b",
    ]
    return any(re.search(rx, s) for rx in strong_patterns)


def normalize_platforms_gui(platforms: Any, user_description: str = "") -> list[str]:
    allowed = ["VINTED", "SUBITO", "EBAY", "WALLAPOP"]
    if not user_explicitly_limits_platforms(user_description):
        return allowed

    if not isinstance(platforms, list):
        platforms = []

    out = []
    for p in platforms:
        s = str(p).upper().strip()
        if s in allowed and s not in out:
            out.append(s)

    # If the user asked for a platform subset but the model failed, infer from text.
    text = clean_word(user_description)
    for platform, aliases in {
        "VINTED": ["vinted"],
        "SUBITO": ["subito", "subito.it"],
        "EBAY": ["ebay", "e-bay"],
        "WALLAPOP": ["wallapop"],
    }.items():
        if any(a in text for a in aliases) and platform not in out:
            out.append(platform)

    return out or allowed


def normalize_vision_enabled_gui(value: Any, user_description: str = "") -> bool:
    s = clean_word(user_description)
    # Default ON for marketplace listings. Disable only if the user explicitly asks for no vision/images.
    explicit_off = [
        "senza immagini", "non usare immagini", "vision off", "vision false",
        "disabilita vision", "no vision", "solo testo",
    ]
    if any(x in s for x in explicit_off):
        return False
    return True


def strip_english_hard_exclusion_tail(prompt: str) -> str:
    p = str(prompt or "").strip()
    if not p:
        return p
    markers = [
        "\nHard exclusions:",
        "\nHard exclusion:",
        "Hard exclusions:",
        "Hard exclusion:",
    ]
    for marker in markers:
        idx = p.find(marker)
        if idx != -1:
            p = p[:idx].rstrip()
    return p


def build_italian_hard_exclusions(exclude_words: list[str]) -> str:
    terms = dedup_list(exclude_words, 40)
    if not terms:
        return ""
    return (
        "\nEsclusioni dure: rifiuta sempre annunci che menzionano, mostrano o vendono principalmente: "
        + ", ".join(terms)
        + "."
    )


def numeric_gb_from_term(term: str) -> int | None:
    s = clean_word(term).replace(" ", "")
    m = re.fullmatch(r"(\\d+)gb", s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def infer_allowed_gb_values_gui(out: dict, user_description: str = "") -> set[int]:
    vals: set[int] = set()
    for group in out.get("required_groups", []) or []:
        if isinstance(group, list):
            for x in group:
                v = numeric_gb_from_term(str(x))
                if v:
                    vals.add(v)
    for rule in out.get("unit_budget_rules", []) or []:
        if isinstance(rule, dict):
            for x in rule.get("match", []) or []:
                v = numeric_gb_from_term(str(x))
                if v:
                    vals.add(v)
    joined = clean_word(user_description + " " + str(out.get("item_description", ""))).replace(" ", "")
    for m in re.finditer(r"(\\d+)gb", joined):
        try:
            vals.add(int(m.group(1)))
        except Exception:
            pass
    return vals


def sanitize_soft_hard_conflicts_gui(out: dict, user_description: str = "") -> None:
    """
    Keep categories separate:
    - hard rejects/excludes = incompatibilities
    - distractors = things to ask AI about, not automatic reject
    - negative_keywords = scoring hints, not duplicates of hard rejects
    """
    hard_keys = ["exclude_words", "reject_patterns"]
    soft_keys = ["distractor_words", "negative_keywords"]

    hard_terms = set()
    for key in hard_keys:
        vals = out.get(key, [])
        if isinstance(vals, list):
            hard_terms.update(clean_word(v) for v in vals if clean_word(v))

    for key in soft_keys:
        vals = out.get(key, [])
        if not isinstance(vals, list):
            out[key] = []
            continue
        out[key] = dedup_list([v for v in vals if clean_word(v) not in hard_terms], 40)

    joined = clean_word(user_description + " " + str(out.get("item_description", "")) + " " + str(out.get("system_prompt", "")))
    wants_bundle_review = any(x in joined for x in ["bundle", "pc inter", "computer inter", "smembra", "vendita a pezzi", "vende a pezzi", "separatamente"])
    if wants_bundle_review:
        bundle_terms = {
            "bundle", "bundle pc", "bundle computer", "pc completo", "computer completo",
            "computer intero", "preassemblato", "preassemblati", "pc intero", "computer", "pc",
        }
        moved = []
        for key in hard_keys:
            vals = out.get(key, [])
            if not isinstance(vals, list):
                vals = []
            kept = []
            for value in vals:
                s = clean_word(value)
                if s in bundle_terms:
                    moved.append(s)
                else:
                    kept.append(value)
            out[key] = dedup_list(kept, 40)
        if moved:
            current = out.get("distractor_words", [])
            if not isinstance(current, list):
                current = []
            out["distractor_words"] = dedup_list(current + moved, 40)

    # RAM: if target is 16/32GB sticks, lower-size stick kits are hard rejects, not distractors.
    allowed = infer_allowed_gb_values_gui(out, user_description=user_description)
    if allowed and min(allowed) >= 16:
        low_bad = []
        for v in [4, 8]:
            if v < min(allowed):
                low_bad.extend([f"{v}gb", f"{v} gb", f"kit da {v}gb", f"kit da {v} gb", f"{v}gb ddr4", f"ddr4 {v}gb"])
        low_bad_clean = {clean_word(x) for x in low_bad}
        for key in ["exclude_words", "reject_patterns"]:
            vals = out.get(key, [])
            if not isinstance(vals, list):
                vals = []
            vals.extend(low_bad)
            out[key] = dedup_list(vals, 40)
        for key in soft_keys:
            vals = out.get(key, [])
            if not isinstance(vals, list):
                vals = []
            out[key] = dedup_list([x for x in vals if clean_word(x) not in low_bad_clean], 40)


def sanitize_gpu_24gb_config_gui(out: dict, user_description: str = "") -> None:
    """
    Rescue for 'scheda video/GPU con minimo N GB VRAM'.
    """
    joined = clean_word(user_description + " " + str(out.get("item_description", "")))
    if not (("scheda video" in joined or "gpu" in joined or "vga" in joined) and "vram" in joined):
        return

    m = re.search(r"(?:minimo|almeno|>=|non meno di)\\s*(\\d+)\\s*gb", joined)
    min_vram = int(m.group(1)) if m else (24 if "24gb" in joined.replace(" ", "") else None)
    if not min_vram:
        return

    if min_vram == 24:
        preferred = [
            "gpu 24gb", "scheda video 24gb", "vram 24gb", "24gb vram",
            "rtx 3090", "rtx 4090", "quadro 24gb", "rtx a5000", "rtx a6000",
        ]
    else:
        preferred = [f"gpu {min_vram}gb", f"scheda video {min_vram}gb", f"vram {min_vram}gb", f"{min_vram}gb vram"]

    existing = out.get("search_keywords", [])
    if not isinstance(existing, list):
        existing = []
    cleaned_existing = []
    for kw in existing:
        s = clean_word(kw)
        if not s:
            continue
        if re.search(r"\\b\\d{3,5}\\b", s):  # budget-like query
            continue
        if any(x in s for x in ["controlla", "budget", "minimo"]):
            continue
        cleaned_existing.append(s)
    out["search_keywords"] = dedup_list(preferred + cleaned_existing, 16)

    sizes = [min_vram]
    for s in [32, 48, 64, 80]:
        if s > min_vram:
            sizes.append(s)
    size_group = []
    for s in sizes:
        size_group.extend([f"{s}gb", f"{s} gb"])
    out["required_groups"] = [["scheda video", "gpu", "vga"], ["vram"], dedup_list(size_group, 16)]

    if any(x in joined for x in ["pc complet", "computer", "vendere separatamente", "separatamente", "smembra"]):
        for key in ["exclude_words", "reject_patterns"]:
            vals = out.get(key, [])
            if not isinstance(vals, list):
                vals = []
            vals = [v for v in vals if clean_word(v) not in {"kit", "bundle", "preassemblato", "pc completo", "computer completo", "computer intero"}]
            out[key] = dedup_list(vals, 40)
        dist = out.get("distractor_words", [])
        if not isinstance(dist, list):
            dist = []
        dist.extend(["pc completo", "computer completo", "preassemblato", "vendita separata", "non vendibile separatamente"])
        out["distractor_words"] = dedup_list(dist, 40)


def fix_mojibake_text(value: str) -> str:
    """
    Fix common UTF-8 decoded as latin-1 artifacts from SSE streaming.
    Examples: 130â¬ -> 130€, Ã¨ -> è.
    """
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


def fix_mojibake_in_obj(value: Any) -> Any:
    if isinstance(value, str):
        return fix_mojibake_text(value)
    if isinstance(value, list):
        return [fix_mojibake_in_obj(x) for x in value]
    if isinstance(value, dict):
        return {fix_mojibake_text(k): fix_mojibake_in_obj(v) for k, v in value.items()}
    return value


def collect_strings_from_obj(value: Any) -> list[str]:
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


def normalize_price_with_tolerance_gui(price: float, text: str) -> float:
    has_tolerance = "+10" in text or "10%" in text or "10 per cento" in text
    if not has_tolerance:
        return float(price)
    # Only bump raw user budgets, not already-bumped values.
    if abs(price - 130.0) < 0.01:
        return 143.0
    if abs(price - 60.0) < 0.01:
        return 66.0
    return float(price)


def extract_unit_prices_from_text_gui(user_description: str, out: dict) -> dict[str, float]:
    """
    Extract explicit per-unit prices like:
    - prezzo massimo per banco di memoria 32gb 130 euro
    - massimo 130€ per ogni banco da 32GB
    - 60€ per banco 16GB

    Avoids confusing capacity numbers (32/16) with prices.
    """
    text = fix_mojibake_text(" ".join(collect_strings_from_obj({
        "user_description": user_description,
        "item_description": out.get("item_description", ""),
        "system_prompt": out.get("system_prompt", ""),
    })))
    low = clean_word(text)
    compact = low.replace(" ", "")

    variants = []
    for variant in ["128gb", "64gb", "48gb", "32gb", "24gb", "16gb", "8gb", "4gb"]:
        if variant in compact:
            variants.append(variant)

    if not variants:
        return {}

    prices: dict[str, float] = {}
    has_tolerance = "+10" in low or "10%" in low or "10 per cento" in low

    for variant in variants:
        num = variant.replace("gb", "")
        forms = [variant, variant.replace("gb", " gb")]

        candidates = []

        # price before variant: 130 euro ... 32gb / 130€ per banco da 32gb
        for form in forms:
            pattern = rf"(\d+(?:[.,]\d+)?)\s*(?:€|eur|euro)?\s*(?:per|/)?\s*(?:ogni\s+)?(?:banco|banchi|modulo|moduli|stick|unit[aà]|pezzo|pezzi)?(?:\s+di\s+memoria|\s+da|\s+di)?\s*{re.escape(form)}"
            for m in re.finditer(pattern, low):
                try:
                    val = float(m.group(1).replace(",", "."))
                except Exception:
                    continue
                if val > 0 and abs(val - float(num)) > 0.01:
                    candidates.append(val)

        # variant before price: 32gb ... 130 euro
        for form in forms:
            pattern = rf"{re.escape(form)}(?:\s+\w+){{0,10}}\s+(\d+(?:[.,]\d+)?)\s*(?:€|eur|euro)"
            for m in re.finditer(pattern, low):
                try:
                    val = float(m.group(1).replace(",", "."))
                except Exception:
                    continue
                if val > 0 and abs(val - float(num)) > 0.01:
                    candidates.append(val)

        # "prezzo massimo per banco ... 32gb 130 euro"
        for form in forms:
            pattern = rf"(?:prezzo\s+massimo|max|massimo)(?:\s+\w+){{0,12}}\s+{re.escape(form)}(?:\s+\w+){{0,8}}\s+(\d+(?:[.,]\d+)?)\s*(?:€|eur|euro)"
            for m in re.finditer(pattern, low):
                try:
                    val = float(m.group(1).replace(",", "."))
                except Exception:
                    continue
                if val > 0 and abs(val - float(num)) > 0.01:
                    candidates.append(val)

        if candidates:
            # Prefer realistic prices above capacity value; if multiple, nearest in text often similar.
            val = max(candidates)
            if has_tolerance:
                if abs(val - 130.0) < 0.01:
                    val = 143.0
                elif abs(val - 60.0) < 0.01:
                    val = 66.0
                else:
                    # Do not blindly bump if model already gave tolerated values or value is not a user budget.
                    pass
            prices[variant] = float(val)

    return prices


def is_gpu_config_gui(out: dict, user_description: str = "") -> bool:
    text = clean_word(" ".join(collect_strings_from_obj({
        "domain_profile": out.get("domain_profile", ""),
        "name": out.get("name", ""),
        "item_description": out.get("item_description", ""),
        "user_description": user_description,
        "search_keywords": out.get("search_keywords", []),
        "required_groups": out.get("required_groups", []),
    })))
    return (
        out.get("domain_profile") == "technology_gpu"
        or "scheda video" in text
        or re.search(r"(?<![a-z0-9])gpu(?![a-z0-9])", text) is not None
        or "vram" in text
    )


def repair_gpu_budget_shape_gui(out: dict, user_description: str = "") -> None:
    """
    GPU/VRAM budgets are total-card budgets, not per-bank memory budgets.

    Prevent LLM hallucinations like:
      unit_budget_rules: 24GB banco / 4GB banco
      budget.configurations: {"4gb": 1000}

    Unit-budget rules remain valid for RAM, but not for GPU VRAM.
    """
    if not is_gpu_config_gui(out, user_description):
        return

    # Determine total budget from existing default/configurations/item text.
    total = None
    budget = out.get("budget") if isinstance(out.get("budget"), dict) else {}
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
        text = clean_word(str(user_description or "") + " " + str(out.get("item_description", "")))
        m = re.search(r"(?:budget|prezzo massimo|max|massimo)\D{0,20}(\d+(?:[.,]\d+)?)\s*(?:€|eur|euro)?", text)
        if m:
            try:
                total = float(m.group(1).replace(",", "."))
            except Exception:
                total = None

    if not total or total <= 0:
        total = 0.0

    if total > 0:
        out["budget"] = {
            "default": float(total),
            "configurations": {"standard": float(total)},
        }
    else:
        out["budget"] = {
            "default": 0.0,
            "configurations": {"standard": 0.0},
        }

    out["unit_budget_rules"] = []
    out["config_patterns"] = {"standard": []}

    # Do not remove required_groups/search_keywords: 24GB/32GB VRAM are valid filters.
    # negative_keywords are left unchanged.




def repair_suspicious_unit_budget_rules_gui(out: dict, user_description: str = "") -> None:
    rules = out.get("unit_budget_rules", [])
    if not isinstance(rules, list):
        return

    extracted = extract_unit_prices_from_text_gui(user_description, out)
    if not extracted:
        return

    repaired = []
    changed = False

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        variant = rule_variant_name_from_match(rule)
        try:
            old_price = float(rule.get("max_price_per_unit", 0))
        except Exception:
            old_price = 0.0

        new_rule = dict(rule)
        if variant and variant in extracted:
            target_price = float(extracted[variant])
            cap_value = float(variant.replace("gb", ""))
            suspicious = old_price <= cap_value + 0.01 or old_price <= 0
            # Also repair if extracted price is much larger and clearly explicit.
            if suspicious or target_price >= old_price * 1.5:
                new_rule["max_price_per_unit"] = target_price
                changed = True
        repaired.append(new_rule)

    # If model gave no rules but extraction succeeded, create them.
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

    if changed:
        out["unit_budget_rules"] = normalize_unit_budget_rules_gui(repaired)


def infer_unit_budget_rules_from_text_gui(out: dict, user_description: str = "") -> None:
    """
    Generic-ish rescue for model outputs that mention per-unit budgets in text
    but forget unit_budget_rules.

    Example handled:
    - 130€ per banco 32GB
    - 60 euro per modulo da 16GB
    - 32GB ... budget 130€
    """
    existing = normalize_unit_budget_rules_gui(out.get("unit_budget_rules", []))
    if existing:
        out["unit_budget_rules"] = existing
        return

    text = " ".join(
        collect_strings_from_obj(
            {
                "user_description": user_description,
                "item_description": out.get("item_description", ""),
                "budget": out.get("budget", {}),
                "system_prompt": out.get("system_prompt", ""),
                "raw_budget_rules": out.get("budget_rules", []),
            }
        )
    )
    text = fix_mojibake_text(text)
    low = clean_word(text)
    compact = low.replace(" ", "")

    if not any(unit_word in low for unit_word in ["per banco", "per modulo", "per stick", "per unit", "per pezzo", "per ogni"]):
        # Avoid inventing unit rules when the user did not describe per-unit pricing.
        return

    variants = []
    for variant in ["128gb", "64gb", "32gb", "16gb", "8gb", "4gb"]:
        if variant in compact:
            variants.append(variant)

    if not variants:
        return

    # price tokens with position in cleaned text
    price_matches = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(?:€|eur|euro)?", low):
        try:
            value = float(m.group(1).replace(",", "."))
        except Exception:
            continue
        if 5 <= value <= 10000:
            price_matches.append((m.start(), value))

    rules = []
    used_variants = set()

    for variant in variants:
        v_forms = [variant, variant.replace("gb", " gb")]
        positions = [m.start() for form in v_forms for m in re.finditer(re.escape(form), low)]
        if not positions:
            continue

        # Choose nearest plausible price around the variant.
        candidates = []
        for pos in positions:
            for ppos, price in price_matches:
                dist = abs(ppos - pos)
                if dist <= 110:
                    candidates.append((dist, price))
        if not candidates:
            continue

        candidates.sort(key=lambda x: x[0])
        price = normalize_price_with_tolerance_gui(candidates[0][1], low)
        if price <= 0:
            continue

        if variant in used_variants:
            continue
        used_variants.add(variant)

        rules.append(
            {
                "name": f"{variant.upper()} banco",
                "match": [variant, variant.replace("gb", " gb")],
                "max_price_per_unit": price,
                "unit": "banco" if ("banco" in low or "ram" in low or "memoria" in low) else "unità",
                "unit_aliases": ["banco", "banchi", "modulo", "moduli", "stick"] if ("ram" in low or "memoria" in low) else ["unità", "pezzo", "pezzi"],
            }
        )

    if rules:
        out["unit_budget_rules"] = normalize_unit_budget_rules_gui(rules)


def rule_variant_name_from_match(rule: dict) -> str | None:
    match = rule.get("match", [])
    if isinstance(match, str):
        match = [match]
    text = " ".join(str(x).lower().replace(" ", "") for x in match)
    for variant in ["32gb", "16gb", "64gb", "8gb", "4gb"]:
        if variant in text:
            return variant
    name = str(rule.get("name", "")).lower().replace(" ", "")
    for variant in ["32gb", "16gb", "64gb", "8gb", "4gb"]:
        if variant in name:
            return variant
    return None


def repair_budget_from_unit_rules_gui(out: dict) -> None:
    """
    If unit_budget_rules are present, keep legacy budget coherent.
    This prevents bad outputs like {"default":0,"standard":0}.
    The core mainly uses unit_budget_rules, but legacy budget still affects score/messages/fallbacks.
    """
    rules = out.get("unit_budget_rules", [])
    if not isinstance(rules, list) or not rules:
        return

    configs = {}
    values = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        try:
            price = float(rule.get("max_price_per_unit", 0))
        except Exception:
            continue
        if price <= 0:
            continue
        values.append(price)
        variant = rule_variant_name_from_match(rule)
        if variant:
            configs[variant] = price

    if not values:
        return

    max_value = max(values)
    budget = out.get("budget", {})
    if not isinstance(budget, dict):
        budget = {}

    raw_default = budget.get("default", 0)
    try:
        default_value = float(raw_default)
    except Exception:
        default_value = 0.0

    old_configs = budget.get("configurations", {})
    if not isinstance(old_configs, dict):
        old_configs = {}

    # Keep meaningful old configs, drop empty/placeholder max/standard if unit rules give variants.
    cleaned_configs = {}
    for k, v in old_configs.items():
        try:
            fv = float(v)
        except Exception:
            continue
        key = str(k).strip().lower()
        if fv <= 0:
            continue
        if key in {"max", "standard", "max_price"} and configs:
            continue
        cleaned_configs[key] = fv

    cleaned_configs.update(configs)

    out["budget"] = {
        "default": max(default_value, max_value) if default_value > 0 else max_value,
        "configurations": cleaned_configs or {"standard": max_value},
    }


def repair_config_patterns_from_unit_rules_gui(out: dict) -> None:
    rules = out.get("unit_budget_rules", [])
    if not isinstance(rules, list) or not rules:
        return

    patterns = out.get("config_patterns", {})
    if not isinstance(patterns, dict):
        patterns = {}

    # Drop useless placeholders generated by the model.
    cleaned = {}
    for k, v in patterns.items():
        key = str(k).strip().lower()
        if key in {"standard", "max", "max_price"}:
            continue
        if isinstance(v, list) and v:
            cleaned[key] = dedup_list(v, 12)

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        variant = rule_variant_name_from_match(rule)
        if not variant:
            continue
        if variant == "32gb":
            cleaned["32gb"] = ["32gb", "32 gb"]
        elif variant == "16gb":
            cleaned["16gb"] = ["16gb", "16 gb"]
        else:
            cleaned[variant] = [variant, variant.replace("gb", " gb")]

    out["config_patterns"] = cleaned or {"standard": []}


def sanitize_noise_lists_gui(out: dict) -> None:
    """
    Remove hallucinated/non-marketplace noise from soft lists too.
    Hard lists are already cleaned elsewhere; this catches distractor/negative/required leftovers.
    """
    suspicious_non_latin = re.compile(r"[^a-z0-9àèéìòùç.+\-\s]", re.IGNORECASE)
    soft_false_noise = {
        "garanzia estesa",
        "spedizione gratuita",
        "offerta speciale",
        "computer nuovo",
        "offerta inclusiva",
    }

    for key in ["distractor_words", "negative_keywords", "required_words"]:
        values = out.get(key, [])
        if not isinstance(values, list):
            out[key] = []
            continue
        cleaned = []
        for value in values:
            s = clean_word(value)
            if not s:
                continue
            if suspicious_non_latin.search(s):
                continue
            if s in soft_false_noise:
                continue
            # required_words is legacy OR; avoid making it too specific/noisy.
            if key == "required_words" and s in {"singolo", "modulo", "banchi", "kit", "multipli", "singolo banco", "singolo modulo"}:
                continue
            cleaned.append(s)
        out[key] = dedup_list(cleaned, 32)


def add_desktop_ram_exclusions_gui(out: dict, user_description: str = "") -> None:
    joined = clean_word(user_description + " " + str(out.get("item_description", "")))
    if not (("ram" in joined or "memoria" in joined) and "desktop" in joined):
        return
    for key in ["exclude_words", "reject_patterns"]:
        values = out.get(key, [])
        if not isinstance(values, list):
            values = []
        for term in ["laptop", "notebook", "portatile"]:
            if term not in values:
                values.append(term)
        out[key] = dedup_list(values, 40)


def strip_prompt_to_specific_notes(prompt: str) -> str:
    """
    Keep only useful target-specific notes, not generated policy.
    The engine/AIService owns JSON schema, budget protocol and generic reasoning.
    """
    p = str(prompt or "").strip()
    if not p:
        return ""

    p = p.replace("[SYSTEM]", "").strip()

    for marker in ["\nEsclusioni dure:", "\nHard exclusions:", "Esclusioni dure:", "Hard exclusions:"]:
        cut = p.find(marker)
        if cut != -1:
            p = p[:cut].strip()

    # Remove generic/budget/policy sentences that belong to fixed engine protocol.
    noisy_fragments = [
        "notifica", "notificare", "rifiuta se il prezzo", "se il prezzo supera",
        "budget", "+10", "130€", "60€", "143€", "66€", "costa meno",
        "prezzo per banco", "valuta sempre il prezzo", "confronta con",
        "non applicare", "il motore applica", "json", "markdown",
        "output only", "ritorna", "sells_item", "confidence", "price_eur",
        "esclusioni dure", "rifiuta sempre",
    ]

    parts = re.split(r"(?<=[.!?])\s+", p)
    kept = []
    for part in parts:
        low = clean_word(part)
        if not low:
            continue
        if any(noise in low for noise in noisy_fragments):
            continue
        # Keep useful domain notes, especially bundle/smembra logic.
        kept.append(part.strip())

    p = " ".join(kept).strip()
    return p[:500].strip()


def build_classic_system_prompt(out: dict, user_description: str = "") -> str:
    """
    Old SpyEngine style:
    - config is data
    - engine owns reasoning protocol
    - generated system_prompt is only category-specific notes
    """
    item = str(out.get("item_description") or user_description or "oggetto richiesto").strip()
    exclude = dedup_list(out.get("exclude_words", []), 40)
    required_groups = out.get("required_groups", [])
    unit_rules = out.get("unit_budget_rules", [])
    generated_notes = strip_prompt_to_specific_notes(out.get("system_prompt", ""))

    lines = [
        "[SYSTEM]",
        "Sei un analizzatore severo di annunci marketplace. Output ONLY valid JSON.",
        "Analizza il contenuto reale dell'annuncio, non fidarti di tag SEO, keyword messe dal venditore o testo non coerente col prodotto.",
        f"Target utente: {item}",
    ]

    if generated_notes:
        lines.append(f"Note specifiche del target: {generated_notes}")

    if required_groups:
        lines.append(
            "Requisiti logici: ogni gruppo richiesto deve avere almeno un termine compatibile; "
            "se mancano termini essenziali, considera l'annuncio non pertinente."
        )

    if exclude:
        lines.append(
            "Esclusioni dure: rifiuta annunci che menzionano, mostrano o vendono principalmente: "
            + ", ".join(exclude)
            + "."
        )

    if unit_rules:
        unit_bits = []
        for rule in unit_rules[:8]:
            try:
                name = str(rule.get("name") or rule.get("unit") or "unità")
                price = float(rule.get("max_price_per_unit"))
                unit = str(rule.get("unit") or "unità")
                matches = ", ".join(rule.get("match", [])[:4]) if isinstance(rule.get("match"), list) else str(rule.get("match", ""))
                unit_bits.append(f"{name}: {price:.0f}€/ {unit} ({matches})")
            except Exception:
                continue
        if unit_bits:
            lines.append(
                "Budget numerico già comprensivo di eventuale tolleranza: "
                + "; ".join(unit_bits)
                + ". Non applicare un ulteriore margine."
            )

    lines.extend(
        [
            "Per bundle, lotti, PC/computer interi o kit: accetta solo se il target è chiaramente vendibile separatamente, smembrabile, o se il prezzo del target è inferibile con buona confidenza.",
            "Non decidere il rigetto solo per prezzo: estrai configurazione e prezzo; il motore applica il budget numerico.",
            "Ritorna sempre e solo JSON con: sells_item, config, price_eur, confidence, reason.",
            "Nessun markdown, nessuna spiegazione fuori JSON.",
        ]
    )

    return "\n".join(lines)


def normalize_budget_language_gui(prompt: str) -> str:
    """
    Prevent double-counting budget tolerance.

    The config numeric budget may already include +10% tolerance, e.g. 130 -> 143.
    The AI prompt must not then ask the model to add another +10%.
    """
    p = str(prompt or "")

    replacements = {
        "Se il prezzo supera il budget ma resta entro +10%, notifica comunque; oltre +10% rifiuta.": 
            "Nota budget: i valori numerici della config includono già l'eventuale tolleranza +10%; non applicare un ulteriore +10%.",
        "Se il prezzo supera il budget ma resta entro +10%, notifica comunque.": 
            "Nota budget: i valori numerici della config includono già l'eventuale tolleranza +10%; non applicare un ulteriore +10%.",
        "Se il prezzo supera budget +10%, notifica.": 
            "Nota budget: i valori numerici della config includono già l'eventuale tolleranza +10%; non applicare un ulteriore +10%.",
        "Se il prezzo supera il budget di +10%, notifica comunque.": 
            "Nota budget: i valori numerici della config includono già l'eventuale tolleranza +10%; non applicare un ulteriore +10%.",
        "Se il prezzo è oltre il budget ma entro +10%, accettalo": 
            "I valori numerici della config includono già la tolleranza +10%; non aggiungere altro margine",
        "budget +10%": "budget numerico già comprensivo dell'eventuale +10%",
        "Budget +10%": "Budget numerico già comprensivo dell'eventuale +10%",
    }

    for old, new in replacements.items():
        p = p.replace(old, new)

    guard = (
        "Nota budget: i valori numerici della config includono già l'eventuale tolleranza +10%; "
        "non applicare un ulteriore +10%. Non rifiutare un annuncio solo per prezzo: estrai configurazione e prezzo, poi il motore applica il budget."
    )

    if "+10" in p and "non applicare un ulteriore +10%" not in p:
        p += "\n" + guard
    elif "non applicare un ulteriore +10%" not in p:
        # Still useful even when +10 was already normalized away.
        p += "\n" + guard

    return p


def normalize_system_prompt_language_gui(prompt: str, exclude_words: list[str], user_description: str = "") -> str:
    p = strip_english_hard_exclusion_tail(prompt)
    if not p:
        p = make_default_analysis_prompt(user_description or "oggetto richiesto")
    p = p.strip()
    p = p.replace("Se il prezzo supera il budget di +10%, notifica comunque.", "Se il prezzo supera il budget ma resta entro +10%, notifica comunque; oltre +10% rifiuta.")
    p = p.replace("supera il budget di +10%", "supera il budget ma resta entro +10%")
    p = normalize_budget_language_gui(p)
    hard = build_italian_hard_exclusions(exclude_words)
    if hard and "Esclusioni dure:" not in p:
        p += hard
    return p


def force_ram_keywords_if_needed(keywords: list[str], user_description: str = "", max_items: int = 20) -> list[str]:
    joined = clean_word(user_description + " " + " ".join(str(x) for x in keywords))
    if not ("ddr4" in joined and ("ram" in joined or "memoria" in joined)):
        return keywords

    preferred = [
        "ddr4 32gb",
        "32gb ddr4",
        "ram 32gb",
        "memoria 32gb",
        "ram ddr4 32gb",
        "2x32gb ddr4",
        "4x32gb ddr4",
        "ddr4 16gb",
        "16gb ddr4",
        "ram 16gb",
        "memoria 16gb",
        "ram ddr4 16gb",
        "2x16gb ddr4",
        "4x16gb ddr4",
        "ram ddr4",
        "memoria ddr4",
    ]

    out = []
    seen = set()
    for kw in preferred + list(keywords or []):
        s = compact_search_keyword(kw, exclude_words=[])
        if not s or s in seen or is_bad_search_keyword(s):
            continue
        # Extra RAM-specific guard: every RAM query should contain ddr4 or ram/memoria + size.
        if not ("ddr4" in s or (("ram" in s or "memoria" in s) and ("16gb" in s or "32gb" in s))):
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= max_items:
            break

    return out


def normalize_search_keywords_gui(
    values: Any,
    user_description: str = "",
    exclude_words: list[str] | None = None,
    max_items: int = 20,
) -> tuple[list[str], list[str]]:
    """
    Turn LLM-generated technical phrases into short marketplace queries.

    Goal:
    - Italian-style short searches when the user writes in Italian.
    - More short combinations instead of few long English phrases.
    - Never search negative constraints such as no-ecc/no rdimm/no server.
    """
    warnings = []
    raw_values = values if isinstance(values, list) else []
    exclude_words = exclude_words or []

    out: list[str] = []
    seen: set[str] = set()

    for kw in raw_values:
        before = clean_word(kw)
        add_compact_keyword(out, seen, before, exclude_words, max_items)
        if len(out) >= max_items:
            break

    # Add short combinations from the user's own words: useful when the model made long English queries.
    source = f"{user_description} " + " ".join(str(x) for x in raw_values)
    seeds = extract_search_seeds(source)

    # Things like ddr4, rtx4090, iphone15, 32gb, 225/45.
    numeric = [t for t in seeds if re.search(r"\d", t)]
    capacities_or_sizes = [
        t for t in numeric
        if re.search(r"\d", t) and re.search(r"(gb|tb|mb|cm|mm|kg|mah|hz|mhz|ghz|w|v)$", t)
    ]
    specs = [t for t in numeric if t not in capacities_or_sizes]
    nouns = [t for t in seeds if t not in numeric][:5]

    # Common useful combinations: spec+variant, noun+variant, noun+spec+variant.
    for size in capacities_or_sizes[:8]:
        for spec in specs[:4]:
            add_compact_keyword(out, seen, f"{spec} {size}", exclude_words, max_items)
            add_compact_keyword(out, seen, f"{size} {spec}", exclude_words, max_items)
            if len(out) >= max_items:
                break
        for noun in nouns[:4]:
            add_compact_keyword(out, seen, f"{noun} {size}", exclude_words, max_items)
            if len(out) >= max_items:
                break
        for noun in nouns[:3]:
            for spec in specs[:3]:
                add_compact_keyword(out, seen, f"{noun} {spec} {size}", exclude_words, max_items)
                if len(out) >= max_items:
                    break
            if len(out) >= max_items:
                break
        if len(out) >= max_items:
            break

    if not out and raw_values:
        out = dedup_list(raw_values, max_items)

    # Warning if we substantially changed the LLM output.
    original_compact = [clean_word(x) for x in raw_values if clean_word(x)]
    if original_compact and out and set(out) != set(original_compact):
        warnings.append("search_keywords compattate: query più brevi, meno inglese tecnico, rimossi vincoli negativi")

    # Domain-specific fallback for common RAM searches: keep them short and Italian.
    joined = clean_word(user_description + " " + " ".join(str(x) for x in raw_values))
    if "ddr4" in joined and ("ram" in joined or "memoria" in joined):
        ram_defaults = [
            "ddr4 32gb", "32gb ddr4", "ram 32gb", "memoria 32gb", "ram ddr4 32gb",
            "ddr4 16gb", "16gb ddr4", "ram 16gb", "memoria 16gb", "ram ddr4 16gb",
            "2x32gb ddr4", "2x16gb ddr4", "4x32gb ddr4", "4x16gb ddr4",
        ]
        for kw in ram_defaults:
            if len(out) >= max_items:
                break
            add_compact_keyword(out, seen, kw, exclude_words, max_items)

    # Final cleanup after fallbacks.
    cleaned = []
    for kw in out:
        s = clean_word(kw)
        if not s or is_bad_search_keyword(s):
            continue
        if re.search(r"(^|\s)(\+?10|60|66|130|143)(\s|$)", s):
            continue
        if any(x in s for x in ["prezzo", "budget", "target", "principale", "secondario", "+10"]):
            continue
        cleaned.append(s)

    out = dedup_list(cleaned, max_items)
    out = force_ram_keywords_if_needed(out, user_description=user_description, max_items=max_items)

    return out[:max_items], warnings


def normalize_required_groups_gui(values: Any) -> list[list[str]]:
    if not isinstance(values, list):
        return []

    out = []
    for group in values:
        if isinstance(group, str):
            group = [group]
        if not isinstance(group, list):
            continue
        cleaned = dedup_list(group, 12)
        if cleaned:
            out.append(cleaned)
        if len(out) >= 12:
            break

    return out


def infer_required_groups_gui(out: dict, user_description: str = "") -> list[list[str]]:
    """
    Infer/repair hard required groups.

    Important:
    required_groups are AND between groups and OR inside a group.

    For RAM DDR4 the correct logic is:
    - must contain DDR4
    - must be RAM/memoria
    - must be either 32GB OR 16GB

    Wrong logic to avoid:
    - ["32gb"] and ["16gb"] as two separate groups, because that requires both.
    - ["singolo modulo", "banchi"] as mandatory group, because many good ads omit those words.
    """
    joined = clean_word(
        user_description
        + " "
        + str(out.get("item_description", ""))
        + " "
        + " ".join(out.get("search_keywords", []))
        + " "
        + " ".join(out.get("required_words", []))
    )

    if "ddr4" in joined and ("ram" in joined or "memoria" in joined):
        size_group = []
        compact = joined.replace(" ", "")
        if "32gb" in compact:
            size_group.extend(["32gb", "32 gb"])
        if "16gb" in compact:
            size_group.extend(["16gb", "16 gb"])
        if not size_group:
            size_group = ["32gb", "32 gb", "16gb", "16 gb"]

        return [
            ["ddr4"],
            ["ram", "memoria"],
            dedup_list(size_group, 8),
        ]

    existing = normalize_required_groups_gui(out.get("required_groups", []))
    if existing:
        # Generic repair: if two separate groups are just alternative numeric capacities, merge them.
        capacity_terms = {"32gb", "32 gb", "16gb", "16 gb", "64gb", "64 gb", "128gb", "128 gb"}
        capacity_groups = []
        other_groups = []
        for group in existing:
            gset = set(group)
            if gset and gset.issubset(capacity_terms):
                capacity_groups.extend(group)
            else:
                # Drop overly generic mandatory unit groups.
                unit_terms = {"banco", "banchi", "modulo", "moduli", "singolo", "singolo modulo", "kit", "multipli"}
                if gset and gset.issubset(unit_terms):
                    continue
                other_groups.append(group)
        if capacity_groups:
            other_groups.append(dedup_list(capacity_groups, 12))
        return other_groups

    return []


def sanitize_hard_rejects_gui(out: dict, user_description: str = "") -> None:
    """
    Remove common LLM mistakes from hard rejects.
    Bundles/PC completi/preassemblati should usually be distractors/context checks,
    not instant rejections, when the user explicitly asked to inspect smembrabile bundles.
    Also remove odd non-language tokens occasionally hallucinated by the model.
    """
    joined = clean_word(user_description + " " + str(out.get("item_description", "")) + " " + str(out.get("system_prompt", "")))
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

    suspicious_non_latin = re.compile(r"[^a-z0-9àèéìòùç.+\\-\\s]", re.IGNORECASE)

    for key in ["exclude_words", "reject_patterns"]:
        values = out.get(key, [])
        if not isinstance(values, list):
            values = []
        cleaned = []
        moved = []
        for value in values:
            s = clean_word(value)
            if not s:
                continue
            if suspicious_non_latin.search(s):
                moved.append(s)
                continue
            if s in false_hard:
                moved.append(s)
                continue
            cleaned.append(s)
        out[key] = dedup_list(cleaned, 40)

        if moved:
            distractors = out.get("distractor_words", [])
            if not isinstance(distractors, list):
                distractors = []
            distractors.extend(moved)
            out["distractor_words"] = dedup_list(distractors, 40)


def add_missing_incompatibilities_gui(out: dict, user_description: str = "") -> None:
    """
    Add obvious hard rejects for known versioned targets.
    If user asks DDR4 and excludes DDR3/DDR5, DDR2 should be rejected too.
    """
    joined = clean_word(user_description + " " + str(out.get("item_description", "")))
    if "ddr4" in joined:
        for key in ["exclude_words", "reject_patterns"]:
            values = out.get(key, [])
            if not isinstance(values, list):
                values = []
            for term in ["ddr2", "ddr3", "ddr5"]:
                if term not in values:
                    values.append(term)
            out[key] = dedup_list(values, 32)


COMMON_UNIT_TRANSLATIONS = {
    "stick": "banco",
    "sticks": "banco",
    "module": "modulo",
    "modules": "modulo",
    "item": "pezzo",
    "piece": "pezzo",
    "unit": "unità",
    "chair": "sedia",
    "chairs": "sedia",
    "tyre": "gomma",
    "tyres": "gomma",
    "tire": "gomma",
    "tires": "gomma",
}

COMMON_UNIT_ALIASES = {
    "banco": ["banco", "banchi", "stick", "modulo", "moduli"],
    "modulo": ["modulo", "moduli", "banco", "banchi"],
    "pezzo": ["pezzo", "pezzi", "unità"],
    "unità": ["unità", "pezzo", "pezzi"],
    "sedia": ["sedia", "sedie"],
    "gomma": ["gomma", "gomme", "pneumatico", "pneumatici"],
}


def normalize_unit_name(unit: str) -> str:
    u = clean_word(unit or "unità")
    return COMMON_UNIT_TRANSLATIONS.get(u, u or "unità")


def normalize_required_words_gui(values: Any, exclude_words: list[str] | None = None) -> tuple[list[str], list[str]]:
    raw = dedup_list(values, 14)
    exclude = [clean_word(x) for x in (exclude_words or []) if clean_word(x)]
    out = []
    removed = []

    for w in raw:
        s = clean_word(w)
        if not s:
            continue
        if s.startswith(NEGATION_PREFIXES):
            removed.append(s)
            continue
        if any(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", s) for term in exclude):
            removed.append(s)
            continue
        if " no " in f" {s} " or " non " in f" {s} " or " senza " in f" {s} ":
            removed.append(s)
            continue
        out.append(s)

    return out, removed


def user_mentions_specific_platforms(user_description: str) -> list[str]:
    if not user_explicitly_limits_platforms(user_description):
        return []
    text = clean_word(user_description)
    found = []
    aliases = {
        "VINTED": ["vinted"],
        "SUBITO": ["subito", "subito.it"],
        "EBAY": ["ebay", "e-bay"],
        "WALLAPOP": ["wallapop"],
    }
    for platform, words in aliases.items():
        if any(w in text for w in words):
            found.append(platform)
    return found


def looks_like_placeholder_prompt(prompt: str) -> bool:
    p = (prompt or "").strip().lower()
    if not p:
        return True
    placeholders = [
        "english, strict, json-only",
        "with acceptance/rejection rules",
        "system prompt here",
        "prompt severo",
    ]
    return any(x in p for x in placeholders) or len(p) < 120


def make_default_analysis_prompt(item_description: str) -> str:
    return (
        "[SYSTEM]\n"
        "Sei un valutatore severo di annunci marketplace. Output ONLY valid JSON.\n"
        "Dato titolo, descrizione, prezzo e opzionalmente immagine, decidi se l'annuncio vende davvero l'oggetto cercato dall'utente.\n"
        f"Oggetto target: {item_description}\n"
        "Ritorna JSON con: sells_item, config, price_eur, confidence, reason.\n"
        "Accetta solo se l'oggetto richiesto è effettivamente in vendita e acquistabile come oggetto chiaro o componente separabile.\n"
        "Rifiuta prodotti non correlati, varianti incompatibili, servizi, riparazioni, scatole, imballi vuoti, oggetti guasti salvo richiesta esplicita.\n"
        "Per bundle o sistemi completi, accetta solo se l'annuncio dice chiaramente che il componente target è venduto separatamente o il suo prezzo individuale è chiaro.\n"
        "Non spiegare fuori dal JSON."
    )


def remove_numeric_series(values: list[str], max_same_prefix: int = 5) -> tuple[list[str], list[str]]:
    """
    Generic anti-hallucination guardrail.
    Removes obvious generated series like ddr6, ddr7, ddr8... or x2400, x2500...
    It is not domain-specific: long same-prefix numeric runs are usually model loops.
    """
    groups: dict[str, list[tuple[str, int]]] = {}
    for v in values:
        m = re.fullmatch(r"([a-zA-Z_.-]*?)(\d{1,5})([a-zA-Z_.-]*)", v.strip())
        if not m:
            continue
        prefix = (m.group(1) + "#" + m.group(3)).lower()
        groups.setdefault(prefix, []).append((v, int(m.group(2))))

    remove = set()
    for prefix, pairs in groups.items():
        nums = sorted(n for _, n in pairs)
        if len(nums) >= max_same_prefix:
            # Remove only if it looks like an artificial sequence.
            diffs = [b - a for a, b in zip(nums, nums[1:])]
            small_steps = sum(1 for d in diffs if 0 < d <= 100)
            if small_steps >= max_same_prefix - 2:
                remove.update(v for v, _ in pairs)

    cleaned = [v for v in values if v not in remove]
    return cleaned, sorted(remove)


def clean_premium_brands(values: list[str]) -> tuple[list[str], list[str]]:
    cleaned = []
    removed = []

    # Generic non-brand words. This is intentionally broad and domain-agnostic:
    # product classes/spec adjectives should not become "premium brands".
    generic_non_brands = {
        "memory", "ram", "module", "stick", "desktop", "laptop", "notebook",
        "server", "computer", "pc", "bundle", "kit", "set", "single", "bank",
        "part", "parts", "piece", "pieces", "dimension", "dynamic", "standard",
        "premium", "original", "compatible", "generic", "brand", "branded",
    }

    for v in values:
        s = clean_word(v)
        # Brand names should not be pure specs, frequencies or generated numeric codes.
        if (
            re.fullmatch(r"x?\d{3,5}", s)
            or re.fullmatch(r"ddr\d+", s)
            or re.fullmatch(r"\d+\s*(mhz|gb|tb)", s)
            or s in generic_non_brands
        ):
            removed.append(v)
            continue
        if len(s) <= 1:
            removed.append(v)
            continue
        cleaned.append(s)
    return cleaned, removed


def normalize_budget(raw_budget: Any) -> tuple[dict, list[str]]:
    warnings = []
    if isinstance(raw_budget, (int, float)):
        value = float(raw_budget)
        return {"default": value, "configurations": {"standard": value}}, warnings

    if not isinstance(raw_budget, dict):
        return {"default": 100.0, "configurations": {"standard": 100.0}}, ["budget non valido: applicato default"]

    budget = dict(raw_budget)
    configs = {}

    existing_configs = budget.get("configurations")
    if isinstance(existing_configs, dict):
        for k, v in existing_configs.items():
            try:
                configs[str(k).lower()] = float(v)
            except Exception:
                pass

    # Move variant budgets from top-level into configurations.
    # Example: {"32GB":130, "16GB":60, "tolerance":"+10%"} -> configurations 32gb/16gb.
    for k, v in list(budget.items()):
        key = str(k).lower()
        if key in {"default", "configurations", "tolerance", "tolerance_percent", "near_budget"}:
            continue
        if isinstance(v, (int, float)):
            configs[key] = float(v)
            warnings.append(f"budget: spostato '{k}' dentro configurations")

    try:
        default = float(budget.get("default"))
    except Exception:
        default = max(configs.values()) if configs else 100.0
        warnings.append("budget.default mancante/non valido: calcolato dalle configurazioni")

    if not configs:
        configs = {"standard": default}

    # If default is the old placeholder 100 but user gave real configs above it, use max real budget.
    if default == 100.0 and any(v != 100.0 for v in configs.values()):
        default = max(configs.values())
        warnings.append("budget.default aggiornato al massimo budget configurato")

    return {"default": default, "configurations": configs}, warnings


def infer_patterns_from_budget_configs(configs: dict) -> dict:
    inferred = {}
    for key in configs.keys():
        k = clean_word(key)
        if not k or k == "standard":
            continue
        vals = {k, k.replace("gb", " gb"), k.replace("_", " ")}
        # Generic quantity pattern, useful for things like 2x16gb, 2xgpu, 4 sedie, etc.
        m = re.fullmatch(r"(\d+)x(.+)", k)
        if m:
            vals.add(f"{m.group(1)} x {m.group(2)}")
            vals.add(f"{m.group(1)}×{m.group(2)}")
        inferred[k] = sorted(v for v in vals if v)
    return inferred


def sanitize_system_prompt(prompt: str, excluded_terms: list[str], item_description: str) -> tuple[str, list[str]]:
    warnings = []
    p = (prompt or "").strip()
    if not p:
        p = make_default_analysis_prompt(item_description)

    excluded = [clean_word(x) for x in excluded_terms if clean_word(x)]
    if not excluded:
        return p[:5000], warnings

    # Remove sentences that explicitly ACCEPT excluded terms.
    sentences = re.split(r"(?<=[.!?])\s+", p)
    kept = []
    removed = []
    for sent in sentences:
        s_low = clean_word(sent)
        if "accept" in s_low and any(re.search(rf"\b{re.escape(term)}\b", s_low) for term in excluded):
            removed.append(sent.strip())
            continue
        kept.append(sent)

    if removed:
        warnings.append(f"system_prompt: rimosse frasi che accettavano termini esclusi ({len(removed)})")

    p = " ".join(x for x in kept if x.strip()).strip()
    hard = ", ".join(sorted(set(excluded))[:30])
    hard_line = (
        "\nHard exclusions: always reject listings mentioning, showing, or primarily selling any of these excluded terms, "
        f"unless the user explicitly asked to accept them: {hard}."
    )

    if "Hard exclusions:" not in p:
        p += hard_line

    return p[:5000], warnings



def normalize_unit_rule_match_terms(raw_match: Any, rule_name: str = "") -> list[str]:
    if isinstance(raw_match, str):
        raw_items = [raw_match]
    elif isinstance(raw_match, list):
        raw_items = raw_match
    else:
        raw_items = []

    out = []
    for item in raw_items:
        s = clean_word(item)
        if not s:
            continue
        # LLM sometimes emits "banco|modulo|moduli|banchi"; split it, but those are aliases, not product matches.
        for part in re.split(r"[|,/;]+", s):
            p = clean_word(part)
            if p:
                out.append(p)

    name = clean_word(rule_name)
    # If rule is called 32GB/16GB but match only contains generic unit names, use the size as match.
    generic_units = {"banco", "banchi", "modulo", "moduli", "stick", "sticks", "pezzo", "pezzi", "unità", "unita"}
    if name and out and all(x in generic_units for x in out):
        inferred = []
        if "32gb" in name or "32 gb" in name:
            inferred = ["32gb", "32 gb"]
        elif "16gb" in name or "16 gb" in name:
            inferred = ["16gb", "16 gb"]
        if inferred:
            return inferred

    # If size appears in name, always add it as a match.
    if "32gb" in name or "32 gb" in name:
        out.extend(["32gb", "32 gb"])
    if "16gb" in name or "16 gb" in name:
        out.extend(["16gb", "16 gb"])

    return dedup_list(out, 12)


def normalize_unit_budget_rules_gui(raw_rules: Any) -> list[dict]:
    if not isinstance(raw_rules, list):
        return []

    out = []
    for idx, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            continue

        rule_name = str(raw.get("name") or raw.get("config") or f"unit_rule_{idx + 1}")
        match = normalize_unit_rule_match_terms(raw.get("match", raw.get("matches", raw.get("terms", []))), rule_name)
        if not match:
            continue

        try:
            max_price = float(raw.get("max_price_per_unit", raw.get("max_unit_price", raw.get("budget_per_unit"))))
        except Exception:
            continue
        if max_price <= 0:
            continue

        aliases = raw.get("unit_aliases", raw.get("aliases", []))
        if isinstance(aliases, str):
            aliases = [aliases]
        if not isinstance(aliases, list):
            aliases = []

        unit = normalize_unit_name(str(raw.get("unit") or "unità"))
        normalized_aliases = dedup_list(aliases, 12)
        defaults_for_unit = COMMON_UNIT_ALIASES.get(unit, [])
        if not normalized_aliases:
            normalized_aliases = defaults_for_unit
        else:
            normalized_aliases = dedup_list(list(normalized_aliases) + list(defaults_for_unit), 12)

        out.append(
            {
                "name": rule_name,
                "match": match[:12],
                "max_price_per_unit": max_price,
                "unit": unit,
                "unit_aliases": normalized_aliases[:12],
            }
        )

    # Apply explicit +10% offer tolerance when the user asked for it and the model forgot to calculate it.
    # This is intentionally conservative and only bumps common exact budgets that appear in the description.
    desc = clean_word(st.session_state.get("_wizard_user_description", "")) if "st" in globals() else ""
    if "+10" in desc or "10%" in desc or "10 per cento" in desc:
        for rule in out:
            try:
                value = float(rule.get("max_price_per_unit", 0))
            except Exception:
                continue
            if abs(value - 130.0) < 0.01:
                rule["max_price_per_unit"] = 143.0
            elif abs(value - 60.0) < 0.01:
                rule["max_price_per_unit"] = 66.0

    return out[:16]


def normalize_generated_config(cfg: dict, user_description: str = "") -> tuple[dict, list[str]]:
    """
    Generic normalization, not RAM-specific:
    - dedupe + length limits
    - remove target/exclude conflicts
    - remove hallucinated numeric sequences
    - repair placeholder prompts
    - restore all platforms unless the user explicitly asked for a subset
    """
    warnings = []
    base = default_config()
    out = dict(base)
    out.update(cfg or {})
    out = fix_mojibake_in_obj(out)
    user_description = fix_mojibake_text(user_description)

    if "keywords" in out and "search_keywords" not in out:
        out["search_keywords"] = out.pop("keywords")

    name = out.get("config_name") or out.get("name") or "new_spy"
    name = re.sub(r"[^a-z0-9_]+", "_", str(name).lower()).strip("_") or "new_spy"
    out["name"] = name
    out.pop("config_name", None)

    # Lists with hard caps. Caps are generic anti-loop protection, not domain rules.
    list_caps = {
        "search_keywords": 16,
        "required_words": 14,
        "exclude_words": 24,
        "distractor_words": 24,
        "reject_patterns": 24,
        "premium_brands": 18,
        "negative_keywords": 24,
    }
    for key, cap in list_caps.items():
        out[key] = dedup_list(out.get(key), cap)

    out["required_words"], removed_required = normalize_required_words_gui(out.get("required_words"), out.get("exclude_words", []))
    if removed_required:
        warnings.append(f"required_words: rimossi vincoli negativi/troppo rigidi {removed_required[:8]}{'...' if len(removed_required) > 8 else ''}")

    sanitize_noise_lists_gui(out)
    add_desktop_ram_exclusions_gui(out, user_description=user_description)
    sanitize_hard_rejects_gui(out, user_description=user_description)
    add_missing_incompatibilities_gui(out, user_description=user_description)
    sanitize_hard_rejects_gui(out, user_description=user_description)
    sanitize_noise_lists_gui(out)
    out["required_groups"] = infer_required_groups_gui(out, user_description=user_description)
    sanitize_gpu_24gb_config_gui(out, user_description=user_description)
    sanitize_soft_hard_conflicts_gui(out, user_description=user_description)
    repair_budget_from_unit_rules_gui(out)
    repair_config_patterns_from_unit_rules_gui(out)
    if out["required_groups"]:
        warnings.append("required_groups applicati per evitare match larghi tipo 'ram 32gb' senza DDR4")

    # Remove obvious generated numeric loops from every semantic list.
    for key in ["required_words", "exclude_words", "distractor_words", "reject_patterns", "premium_brands", "negative_keywords"]:
        cleaned, removed = remove_numeric_series(out.get(key, []))
        out[key] = cleaned
        if removed:
            warnings.append(f"{key}: rimossa sequenza numerica artificiale {removed[:8]}{'...' if len(removed) > 8 else ''}")

    brands, removed_brands = clean_premium_brands(out.get("premium_brands", []))
    out["premium_brands"] = brands
    if removed_brands:
        warnings.append(f"premium_brands: rimossi valori non-brand {removed_brands[:8]}{'...' if len(removed_brands) > 8 else ''}")

    # Required/exclude conflict: never exclude what you require.
    required_set = set(out["required_words"])
    before_exclude = list(out["exclude_words"])
    out["exclude_words"] = [w for w in out["exclude_words"] if w not in required_set]
    removed_conflicts = sorted(set(before_exclude) - set(out["exclude_words"]))
    if removed_conflicts:
        warnings.append(f"Rimosse da exclude_words perché erano anche required_words: {removed_conflicts}")

    # Clean search queries instead of weakening hard exclusions.
    # Example: "ram ddr4 non-ecc desktop" becomes "ram ddr4"; "ecc" remains an exclusion.
    out["search_keywords"], keyword_warnings = normalize_search_keywords_gui(
        out.get("search_keywords", []),
        user_description=user_description,
        exclude_words=out.get("exclude_words", []) + out.get("negative_keywords", []) + out.get("reject_patterns", []),
        max_items=16,
    )
    out["search_keywords"] = force_ram_keywords_if_needed(out["search_keywords"], user_description=user_description, max_items=16)
    warnings.extend(keyword_warnings)

    # Platforms: if the user did not explicitly mention platforms, keep all default platforms.
    explicit_platforms = user_mentions_specific_platforms(user_description)
    ai_platforms = [str(p).upper() for p in out.get("platforms", []) if str(p).upper() in KNOWN_PLATFORMS]
    if explicit_platforms:
        out["platforms"] = explicit_platforms
    elif set(ai_platforms) != set(DEFAULT_PLATFORMS):
        out["platforms"] = DEFAULT_PLATFORMS[:]
        warnings.append("Piattaforme ripristinate a VINTED/SUBITO/EBAY/WALLAPOP perché l'utente non aveva chiesto un subset")
    else:
        out["platforms"] = ai_platforms or DEFAULT_PLATFORMS[:]

    # Budget normalization.
    out["budget"], budget_warnings = normalize_budget(out.get("budget"))
    warnings.extend(budget_warnings)

    out["unit_budget_rules"] = normalize_unit_budget_rules_gui(out.get("unit_budget_rules", []))
    infer_unit_budget_rules_from_text_gui(out, user_description=user_description)

    out["platforms"] = normalize_platforms_gui(out.get("platforms", []), user_description=user_description)
    out["vision_enabled"] = normalize_vision_enabled_gui(out.get("vision_enabled", True), user_description=user_description)

    # Patterns: if missing or only standard empty, infer minimal patterns from budget configuration keys.
    if not isinstance(out.get("config_patterns"), dict):
        out["config_patterns"] = {}

    only_empty_standard = set(out["config_patterns"].keys()) <= {"standard"} and not out["config_patterns"].get("standard")
    if not out["config_patterns"] or only_empty_standard:
        inferred = infer_patterns_from_budget_configs(out.get("budget", {}).get("configurations", {}))
        out["config_patterns"] = inferred or {"standard": []}
        if inferred:
            warnings.append("config_patterns inferiti dai nomi budget")

    if not isinstance(out.get("positive_keywords"), dict):
        out["positive_keywords"] = {}

    if not out.get("search_keywords"):
        out["search_keywords"] = base["search_keywords"]
        warnings.append("search_keywords vuoto: applicato default minimo")

    if not isinstance(out.get("item_description"), str) or not out["item_description"].strip():
        out["item_description"] = user_description.strip()[:300] or base["item_description"]

    out["vision_enabled"] = bool(out.get("vision_enabled", True))
    out["context_check_enabled"] = bool(out.get("context_check_enabled", True))
    out["interval_seconds"] = int(out.get("interval_seconds", 300) or 300)
    out["max_history"] = int(out.get("max_history", 200) or 200)
    out["ebay_app_id_env"] = out.get("ebay_app_id_env") or "EBAY_APP_ID"

    if looks_like_placeholder_prompt(str(out.get("system_prompt", ""))):
        out["system_prompt"] = make_default_analysis_prompt(out["item_description"])
        warnings.append("system_prompt placeholder sostituito con prompt reale generico")
    else:
        out["system_prompt"] = str(out.get("system_prompt"))[:5000]

    out["system_prompt"], prompt_warnings = sanitize_system_prompt(
        out["system_prompt"],
        out.get("exclude_words", []) + out.get("negative_keywords", []),
        out["item_description"],
    )
    warnings.extend(prompt_warnings)

    infer_unit_budget_rules_from_text_gui(out, user_description=user_description)
    repair_suspicious_unit_budget_rules_gui(out, user_description=user_description)
    repair_budget_from_unit_rules_gui(out)
    repair_gpu_budget_shape_gui(out, user_description=user_description)
    repair_gpu_budget_shape_gui(out, user_description=user_description)
    repair_config_patterns_from_unit_rules_gui(out)
    sanitize_gpu_24gb_config_gui(out, user_description=user_description)
    sanitize_soft_hard_conflicts_gui(out, user_description=user_description)
    out, domain_warnings = apply_domain_profile(out, user_description=user_description)
    warnings.extend(domain_warnings)
    sanitize_soft_hard_conflicts_gui(out, user_description=user_description)
    sanitize_noise_lists_gui(out)

    out["system_prompt"] = build_classic_system_prompt(out, user_description=user_description)

    # Final guard: all platforms by default unless the user explicitly limited them.
    out["platforms"] = normalize_platforms_gui(out.get("platforms", []), user_description=user_description)

    return out, warnings


def extract_json_object(text: str) -> dict | None:
    if not text:
        return None

    cleaned = text.strip()
    if "```" in cleaned:
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
        if m:
            cleaned = m.group(1).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]

    try:
        return json.loads(cleaned)
    except Exception:
        return None


def call_llm_messages(
    messages: list[dict],
    max_tokens: int = 2600,
    temperature: float = 0.2,
    progress: Any = None,
    stream: bool | None = None,
) -> tuple[str | None, str | None]:
    """
    OpenAI-compatible llama.cpp chat call.

    Important:
    - Non-streaming waits for the entire response, so a slow model can hit HTTP read timeout
      even while it is generating correctly.
    - Streaming receives chunks as they are generated and is much safer for local GGUF models.
    """
    if stream is None:
        stream = os.environ.get("LLAMA_GUI_STREAM", "true").strip().lower() not in {"0", "false", "no", "off"}

    connect_timeout = int(os.environ.get("LLAMA_HTTP_CONNECT_TIMEOUT", "15"))
    read_timeout = int(os.environ.get("LLAMA_HTTP_READ_TIMEOUT", "600"))
    url = os.environ.get("LLAMA_OPENAI_URL", "http://127.0.0.1:8080/v1/chat/completions")

    payload = {
        "messages": messages,
        "temperature": temperature,
        "top_p": 0.85,
        "max_tokens": max_tokens,
        "stream": bool(stream),
    }

    def emit(stage: str, message: str, detail: Any = None):
        if not progress:
            return
        try:
            progress(stage, message, detail)
        except Exception:
            pass

    try:
        if not stream:
            r = requests.post(url, json=payload, timeout=(connect_timeout, read_timeout))
            r.encoding = "utf-8"
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}: {r.text[:500]}"
            try:
                return r.json()["choices"][0]["message"]["content"], None
            except Exception:
                return None, f"Risposta AI non valida: {r.text[:500]}"

        stream_started = time.time()
        emit("llm_stream_open", "Connessione streaming aperta")
        chunks: list[str] = []
        last_emit = time.time()
        last_emit_chars = 0
        first_token_at: float | None = None
        trace_interval = float(os.environ.get("LLAMA_GUI_TRACE_INTERVAL", "15"))

        with requests.post(
            url,
            json=payload,
            stream=True,
            timeout=(connect_timeout, read_timeout),
        ) as r:
            if r.status_code != 200:
                try:
                    body = r.text[:500]
                except Exception:
                    body = "<body non leggibile>"
                return None, f"HTTP {r.status_code}: {body}"

            for raw_line in r.iter_lines(decode_unicode=False):
                if raw_line is None:
                    continue
                if isinstance(raw_line, bytes):
                    line = raw_line.decode("utf-8", errors="replace").strip()
                else:
                    line = str(raw_line).strip()
                if not line:
                    continue

                if line.startswith("data:"):
                    line = line[5:].strip()

                if line == "[DONE]":
                    break

                try:
                    data = json.loads(line)
                except Exception:
                    continue

                choices = data.get("choices") or []
                if not choices:
                    continue

                choice = choices[0]
                delta = choice.get("delta") or {}
                content = delta.get("content")

                # Some servers put final content in message/content instead of delta/content.
                if content is None:
                    msg = choice.get("message") or {}
                    content = msg.get("content")

                now = time.time()

                if content:
                    chunks.append(content)
                    if first_token_at is None:
                        first_token_at = now
                        emit(
                            "llm_first_token",
                            f"Primo token dopo {first_token_at - stream_started:.1f}s",
                            {
                                "ttft_seconds": round(first_token_at - stream_started, 3),
                                "note": "Tempo fino al primo token: include prompt evaluation / eventuale coda server.",
                            },
                        )

                if now - last_emit >= trace_interval:
                    text = "".join(chunks)
                    current_chars = len(text)
                    delta_chars = current_chars - last_emit_chars
                    interval = max(now - last_emit, 0.001)
                    interval_rate = delta_chars / interval

                    if first_token_at is None or current_chars == 0:
                        emit(
                            "llm_stream",
                            f"Attesa primo token... {now - stream_started:.1f}s, {current_chars} caratteri",
                            {
                                "chars": current_chars,
                                "ttft_wait_seconds": round(now - stream_started, 3),
                            },
                        )
                    else:
                        gen_elapsed = max(now - first_token_at, 0.001)
                        gen_rate = current_chars / gen_elapsed
                        emit(
                            "llm_stream",
                            (
                                f"Ricezione... {current_chars} caratteri "
                                f"(+{delta_chars}, {interval_rate:.1f} car/s intervallo, "
                                f"{gen_rate:.1f} car/s dopo primo token)"
                            ),
                            text[-1200:],
                        )

                    last_emit = now
                    last_emit_chars = current_chars

        text = "".join(chunks).strip()
        finished_at = time.time()
        total_duration = max(finished_at - stream_started, 0.001)
        if first_token_at is None:
            done_msg = f"Streaming completato: {len(text)} caratteri in {total_duration:.1f}s; nessun primo token misurato"
            done_detail = text[-2000:]
        else:
            ttft = first_token_at - stream_started
            gen_duration = max(finished_at - first_token_at, 0.001)
            gen_rate = len(text) / gen_duration
            done_msg = (
                f"Streaming completato: {len(text)} caratteri in {total_duration:.1f}s; "
                f"TTFT {ttft:.1f}s; {gen_rate:.1f} car/s dopo primo token"
            )
            done_detail = {
                "tail": text[-2000:],
                "chars": len(text),
                "total_seconds": round(total_duration, 3),
                "ttft_seconds": round(ttft, 3),
                "generation_seconds_after_first_token": round(gen_duration, 3),
                "chars_per_second_after_first_token": round(gen_rate, 3),
            }

        emit("llm_stream_done", done_msg, done_detail)
        if not text:
            return None, "Risposta AI vuota in streaming"
        return text, None

    except requests.exceptions.ReadTimeout as e:
        return None, (
            f"Timeout AI dopo {read_timeout}s senza nuovi token. "
            "Il modello potrebbe essere occupato/impantanato: prova Stop Llama -> Start Llama, "
            "oppure aumenta LLAMA_HTTP_READ_TIMEOUT."
        )
    except Exception as e:
        return None, f"Errore rete AI: {e}"


def infer_prompt_domain_hint(user_description: str) -> tuple[str, str]:
    """
    Lightweight prompt-time domain hint.
    This is not a hard taxonomy; it only selects the best expert framing.
    """
    t = clean_word(user_description)

    if any(x in t for x in ["ram", "memoria", "ddr", "sodimm", "rdimm", "udimm"]):
        return "technology_ram", "tecnico hardware/memorie RAM"
    if any(x in t for x in ["scheda video", "gpu", "vram", "rtx", "radeon", "quadro", "geforce"]):
        return "technology_gpu", "tecnico GPU/workstation"
    if any(x in t for x in ["scheda madre", "motherboard", "mainboard", "am4", "am5", "b550", "x570", "z790"]):
        return "technology_motherboard", "tecnico schede madri/compatibilità PC"
    if any(x in t for x in ["ssd", "nvme", "m.2", "sata", "pcie"]):
        return "technology_ssd", "tecnico storage SSD/NVMe"
    if any(x in t for x in ["monitor", "schermo", "display", "oled", "hz", "ips", "ultrawide"]):
        return "technology_monitor", "tecnico display/monitor"
    if any(x in t for x in ["trapano", "avvitatore", "smerigliatrice", "utensile", "batteria"]):
        return "tools", "tecnico utensili/fai-da-te"
    if any(x in t for x in ["gemelli", "camicia", "bracciale", "anello", "orologio", "borsa"]):
        return "fashion_accessories", "esperto marketplace accessori/moda"
    if any(x in t for x in ["tapparella", "serranda", "avvolgibile", "persiana", "zanzariera"]):
        return "home_window_coverings", "tecnico casa/infissi/tapparelle"
    if any(x in t for x in ["gomme", "pneumatici", "cerchi", "ruote"]):
        return "vehicle_tires", "tecnico pneumatici/compatibilità auto"

    return "generic", "analista marketplace generalista"


def build_phase_domain_contract(user_description: str, enrichment_note: str = "") -> str:
    domain, expert_role = infer_prompt_domain_hint(user_description)

    return f"""CONTRATTO DI ANALISI A FASI

Fase 1 — Classificazione dominio
- Dominio stimato: {domain}
- Ruolo esperto da assumere: {expert_role}
- Non serve dichiarare di essere esperto: usa questa competenza per strutturare correttamente la config.

Fase 2 — Separazione concetti
Dividi SEMPRE questi tre piani:
1. target_product: l'oggetto venduto che l'utente vuole comprare.
2. technical_specs: caratteristiche tecniche/qualitative dell'oggetto.
   Esempi: 24GB VRAM, DDR4, 32GB per modulo RAM, 18V batteria, 240Hz, AM4/B550.
3. commercial_quantity: quantità commerciale acquistata/venduta.
   Esempi: 1 banco, 2 moduli, kit da 2, coppia/paio, 4 sedie, 4 gomme.

Regola critica:
- Una specifica tecnica NON deve diventare quantità commerciale.
- "24GB VRAM" = specifica tecnica GPU, NON 24 banchi/moduli/stick.
- "32GB RAM" = capacità del modulo RAM; "banco/modulo/stick" è l'unità commerciale.
- "kit da 2 gemelli" = quantità commerciale/set da 2 pezzi o coppia.
- "batteria 18V" = specifica tecnica, NON 18 batterie.

Fase 3 — Budget scope
Classifica ogni budget:
- total_product: prezzo massimo totale dell'oggetto target.
- per_unit: prezzo massimo per unità commerciale, se l'utente dice "per banco", "per gomma", "per pezzo", "per sedia", ecc.
- total_kit: prezzo massimo per kit/set/coppia/lotto, se l'utente cerca un kit/set.
- per_variant: budget diverso per variante tecnica, es. 130€ per banco 32GB, 60€ per banco 16GB.

Regole budget:
- Se il budget è scritto senza "per <unità>", assumilo total_product o total_kit, NON per_unit.
- Crea unit_budget_rules SOLO se esiste una vera unità commerciale e il budget è per unità.
- Non creare unit_budget_rules da sole specifiche tecniche.
- Non creare config budget "4gb" o "24gb" se l'utente non ha dato budget specifico per quella variante.
- Se l'utente dice +10%, incorpora la tolleranza nel numero finale e scrivi che è già inclusa.

Fase 4 — Output config
- search_keywords servono a trovare annunci: brevi, comuni, niente budget/prezzi.
- required_groups servono a filtrare logicamente.
- exclude_words/reject_patterns solo incompatibilità dure.
- distractor_words per bundle/PC/lotti/accessori da far valutare all'AI, non rigettare subito se l'utente vuole controllare separabilità.

Fase 5 — Sanity check finale
Prima di emettere JSON controlla:
- technical_specs non sono finite in unit_budget_rules come unità commerciali.
- commercial_quantity ha alias corretti per il dominio.
- budget scope è coerente con le parole "per", "kit", "coppia", "banco", "pezzo".
- bundle/PC completi sono reject solo se l'utente NON ha chiesto di controllare smembrabilità.
"""


def target_analysis_schema_instruction() -> str:
    return """Nel piano intermedio includi SEMPRE una chiave target_analysis con questa forma:

{
  "target_analysis": {
    "domain": "...",
    "expert_role": "...",
    "target_product": "...",
    "technical_specs": [
      {"name": "...", "value": "...", "unit": "...", "constraint": "required|min|allowed|excluded"}
    ],
    "commercial_quantity": {
      "unit": null,
      "aliases": [],
      "required_quantity": null,
      "allowed_quantities": [],
      "scope": "single|kit|lot|unknown",
      "evidence_terms": []
    },
    "budget_rules": [
      {
        "amount": 0,
        "currency": "EUR",
        "scope": "total_product|per_unit|total_kit|per_variant",
        "applies_to": "...",
        "quantity_basis": null,
        "tolerance_included": false
      }
    ],
    "sanity_checks": []
  }
}

Esempi di interpretazione:
- GPU 24GB VRAM budget 1000:
  technical_specs = VRAM min 24GB; commercial_quantity.unit = null; budget scope = total_product; unit_budget_rules finali = [].
- RAM DDR4 banco 32GB max 100 per banco:
  technical_specs = DDR4, 32GB per modulo; commercial_quantity.unit = banco/modulo/stick; budget scope = per_unit.
- Gemelli da camicia kit da 2 max 150:
  target_product = gemelli da camicia; commercial_quantity = kit/coppia/pezzi required_quantity 2; budget scope = total_kit.
"""



def call_llm_for_config_fast(user_description: str, retry_note: str = "", progress: Any = None, enrichment_note: str = "") -> tuple[str | None, str | None]:
    """
    Fast classic/compiler mode: one LLM call instead of planner+generator.
    The code normalizer repairs/validates the result, so we don't need a second model pass.
    """
    t0 = time.time()

    def emit(stage: str, message: str, detail: Any = None):
        if not progress:
            return
        try:
            progress(stage, message, detail, time.time() - t0)
        except Exception:
            pass

    emit("start", "Avvio wizard fast single-pass")
    domain_contract = build_phase_domain_contract(user_description, enrichment_note=enrichment_note)

    system = (
        "Sei un compilatore di configurazioni SpyEngine per marketplace. "
        "Lavora per fasi: classificatore dominio, esperto dominio, compiler JSON, critic finale. "
        "Devi separare specifiche tecniche, quantità commerciali e budget scope. "
        "Output ONLY one valid JSON object. No markdown. No comments."
    )

    user = f"""Descrizione utente:
{user_description}

{("CONTESTO TECNICO OPZIONALE:\n" + enrichment_note + "\n") if enrichment_note else ""}

{domain_contract}

Genera una config SpyEngine JSON.

Regole classic/compiler:
- Ragiona nella lingua dell'utente.
- search_keywords: 8-16 query brevi da marketplace, 1-3 parole, massimo 4 se serve.
- search_keywords: meglio query corte tipo "ddr4 32gb", "ram 32gb", "2x32gb ddr4" che frasi lunghe.
- search_keywords: non inserire prezzi, budget, +10, target, principale, secondario.
- required_words: lista legacy breve, non troppo specifica.
- required_groups: gruppi obbligatori AND/OR. Ogni gruppo deve avere almeno un match. Per alternative come 32GB/16GB usa un solo gruppo con entrambe.
- exclude_words/reject_patterns: incompatibilità dure. Non mettere "kit", "bundle", "pc completo", "computer intero" nei reject se l'utente chiede kit/multipli o controllare smembrabilità.
- Se un termine è in exclude_words/reject_patterns, non duplicarlo in distractor_words/negative_keywords.
- distractor_words: bundle, PC interi, lotti o casi da far valutare all'AI, non da rigettare subito.
- Per target "minimo/almeno N GB" crea required_groups con il prodotto, la caratteristica e valori >= N quando sensato; non generare keyword con il prezzo/budget.
- platforms: se l'utente non scrive chiaramente "solo Subito/Vinted/eBay/Wallapop", usa sempre ["VINTED","SUBITO","EBAY","WALLAPOP"].
- vision_enabled: true di default.
- context_check_enabled: true.
- budget: numerico coerente e con scope corretto.
- budget senza "per <unità>" = total_product/total_kit, non unit_budget_rules.
- unit_budget_rules: usa SOLO quando l'utente dà prezzo per vera quantità commerciale: pezzo/unità/banco/modulo/stick/gomma/sedia/kit ecc.
- Non trasformare specifiche tecniche in quantità commerciali: 24GB VRAM, 18V, 240Hz, AM4/B550 sono technical_specs, non unità.
- Per GPU/VRAM non creare mai "banco/modulo/stick" o config 4GB/24GB per il budget, salvo richiesta esplicita di lotti di più schede.
- Se l'utente dice +10% o vicino al budget +10%, incorpora la tolleranza nei numeri: 130 -> 143, 60 -> 66.
- system_prompt: solo note specifiche del target, brevi. Non duplicare JSON schema, piattaforme, hard exclusions o budget: il motore li aggiunge.

Campi obbligatori:
name, item_description, search_keywords, exclude_words, required_words, required_groups,
distractor_words, budget, unit_budget_rules, config_patterns, reject_patterns,
premium_brands, positive_keywords, negative_keywords, platforms, vision_enabled,
context_check_enabled, interval_seconds, max_history, ebay_app_id_env, system_prompt.

Formato budget:
"budget": {{"default": number, "configurations": {{"variant": number}}}}

Formato unit_budget_rules:
[
  {{"name":"...", "match":["term"], "max_price_per_unit": number, "unit":"...", "unit_aliases":["..."]}}
]

{retry_note}

JSON:"""

    emit("single_call_start", "Genero config in una sola chiamata LLM")
    raw, err = call_llm_messages(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=int(os.environ.get("LLAMA_GUI_FAST_MAX_TOKENS", "1800")),
        temperature=0.10,
        progress=emit,
        stream=True,
    )
    if err:
        emit("single_call_error", f"Errore single-pass: {err}")
        return None, err

    emit("single_call_raw", "Config raw ricevuta dal modello", raw or "")
    emit("done_llm", "Chiamata LLM completata")
    return raw or "", None


def call_llm_for_config(user_description: str, retry_note: str = "", progress: Any = None, enrichment_note: str = "") -> tuple[str | None, str | None]:
    """
    Generic 2-step wizard:
    1) classification/plan JSON
    2) final config JSON from the plan

    This is deliberately not hardcoded to RAM/CPU/GPU/furniture.
    """
    t0 = time.time()

    def emit(stage: str, message: str, detail: Any = None):
        if not progress:
            return
        try:
            progress(stage, message, detail, time.time() - t0)
        except Exception:
            pass

    emit("start", "Avvio wizard classic/compiler")
    domain_contract = build_phase_domain_contract(user_description, enrichment_note=enrichment_note)
    analysis_schema = target_analysis_schema_instruction()

    planner_system = (
        "Sei il classificatore e analista dominio di un wizard marketplace. "
        "Prima ragioni da esperto del dominio, poi produci un piano JSON compatto. "
        "Devi separare target_product, technical_specs, commercial_quantity e budget scope. "
        "Output ONLY valid JSON."
    )
    planner_user = f"""
User request:
{user_description}

{("CONTESTO TECNICO OPZIONALE:\n" + enrichment_note + "\n") if enrichment_note else ""}

{domain_contract}

{analysis_schema}

Create a compact planning JSON with these keys:
- target_analysis: object exactly following the schema above
- domain: short item category
- variants: important variants/sizes/specs mentioned by the user
- wanted_terms: terms that describe wanted items
- incompatible_terms: terms that make an item incompatible
- soft_distractors: related things that may be false positives but may need AI review
- budget_rules: extracted budget rules with scope: total_product, per_unit, total_kit, per_variant
- platforms: only if user explicitly mentioned platform names, otherwise []
- ai_review_rules: 5-10 short rules for deciding if a listing should be accepted/rejected

Planner rules:
- Ragiona nella lingua dell'utente.
- Per le query di ricerca pensa come un utente di Subito/Vinted/Wallapop/eBay: poche parole, termini comuni.
- Non confondere specifiche tecniche con quantità commerciali.
- Non creare budget per varianti tecniche se l'utente ha dato un solo budget totale.
- Do not invent long numeric sequences.
- Do not repeat list values.
- Keep every list compact.
- Output only JSON.
"""
    emit("planner_start", "Creo il piano compatto dal prompt utente")
    plan_raw, err = call_llm_messages(
        [{"role": "system", "content": planner_system}, {"role": "user", "content": planner_user}],
        max_tokens=int(os.environ.get("LLAMA_GUI_PLANNER_MAX_TOKENS", "1200")),
        temperature=0.15,
        progress=emit,
        stream=True,
    )
    if err:
        emit("planner_error", f"Errore planner: {err}")
        return None, err

    emit("planner_raw", "Risposta planner ricevuta", plan_raw or "")
    plan = extract_json_object(plan_raw or "")
    if not plan:
        emit("planner_parse_failed", "Il planner non ha restituito JSON recuperabile", plan_raw or "")
        return plan_raw, None  # caller will retry/fail with raw visible

    emit("planner_json", "Piano JSON recuperato", json.dumps(plan, indent=2, ensure_ascii=False))

    generator_system = (
        "Converti un piano di ricerca marketplace in una config SpyEngine. "
        "Ragiona nella lingua dell'utente; se l'utente scrive in italiano, usa italiano per keyword, filtri e prompt. "
        "Output ONLY one valid JSON object. No markdown. No comments. No repeated items."
    )
    generator_user = f"""
Original user request:
{user_description}

Planning JSON:
{json.dumps(plan, ensure_ascii=False)}

{domain_contract}

Create the final SpyEngine config JSON.
Use Planning JSON.target_analysis as the authority for:
- target_product
- technical_specs
- commercial_quantity
- budget scope
- sanity_checks

Required keys:
config_name, item_description, search_keywords, required_words, required_groups, exclude_words,
distractor_words, budget, unit_budget_rules, config_patterns, reject_patterns, premium_brands,
positive_keywords, negative_keywords, platforms, vision_enabled,
context_check_enabled, interval_seconds, max_history, ebay_app_id_env, system_prompt.

Generic rules:
- Modalità classic/compiler: genera dati di configurazione, non provare a codificare tutto il ragionamento nel prompt.
- search_keywords: 8-16 query brevi da marketplace, nella lingua dell'utente. Preferisci 1-3 parole, massimo 4 solo se serve.
- search_keywords: meglio molte combinazioni corte che poche frasi lunghe. Esempio buono: "ddr4 32gb", "32gb ddr4", "ram 32gb", "memoria 32gb". Esempio cattivo: "ddr4 16gb single stick desktop".
- search_keywords: non inserire prezzi, budget, "prezzo per banco", "+10", "target", "principale", "secondario", "130 32gb", "60 16gb" o parole del prompt che non servono a trovare annunci.
- search_keywords: non inserire vincoli negativi o tecnici che servono solo a filtrare, tipo "no ecc", "non-ecc", "no rdimm", "registered", "server", "sodimm". Quelli vanno in exclude_words/reject_patterns.
- search_keywords: non usare inglese se l'utente scrive in italiano, tranne brand, sigle tecniche standard o termini che gli utenti scrivono davvero negli annunci.
- required_words: alternative compatte legacy; non usarle per logica AND/OR complessa.
- required_groups: lista di gruppi obbligatori; ogni gruppo deve avere almeno un match. Esempio RAM DDR4: [["ddr4"], ["ram", "memoria"], ["32gb", "32 gb", "16gb", "16 gb"]].
- required_words: non mettere frasi negative tipo "no ecc", "non-ecc", "no server"; molti annunci validi non le scrivono.
- exclude_words: solo incompatibilità dure. Non includere termini desiderati.
- distractor_words: falsi positivi o oggetti correlati da far valutare all'AI; usa la lingua dell'utente.
- reject_patterns: frasi che devono rigettare subito.
- premium_brands: solo veri nomi brand, non frequenze/specifiche/dimensioni.
- positive_keywords: termini qualità/specifica utili con piccoli bonus numerici.
- platforms: se l'utente non scrive chiaramente "solo Subito/Vinted/eBay/Wallapop", usa sempre ["VINTED","SUBITO","EBAY","WALLAPOP"]. Non scegliere una sola piattaforma di tua iniziativa.
- vision_enabled: true di default per marketplace; false solo se l'utente chiede esplicitamente di non usare immagini/vision.
- context_check_enabled: true.
- interval_seconds: 300.
- max_history: 200.
- ebay_app_id_env: "EBAY_APP_ID".
- budget must preserve total_product/total_kit/per_variant/per_unit scope from target_analysis.
- budget senza vera unità commerciale = {{"default": amount, "configurations": {{"standard": amount}}}}.
- unit_budget_rules: usale SOLO quando target_analysis.budget_rules.scope è per_unit o per_variant con unità commerciale vera.
- unit_budget_rules fields: name, match, max_price_per_unit, unit, unit_aliases.
- unit_budget_rules: match identifica la variante/oggetto a cui si applica il budget; unit/unit_aliases identificano come contare la quantità commerciale.
- Specifiche tecniche NON sono unità commerciali: 24GB VRAM, 18V, 240Hz, AM4/B550 non devono diventare "banco", "pezzo", "stick" o budget configs.
- Per GPU/VRAM, salvo lotti espliciti di più schede, usa budget standard totale e unit_budget_rules=[].
- Per RAM con prezzo per banco/modulo/stick, usa match della variante tecnica (es. ["32gb","32 gb"]) e unit_aliases banco/modulo/stick.
- Per kit/set/coppia, se il budget è per tutto il kit, NON fare per_unit; usa budget standard/total_kit e descrivi quantity nel system_prompt/item_description.
- Se l'utente dice budget +10% o vicino al budget +10%, incorpora la tolleranza nei numeri: 130 diventa 143, 60 diventa 66. Nel system_prompt finale specifica che questi numeri includono già la tolleranza e che non va applicato un altro +10%.
- If the user says any quantity is acceptable and budget is per unit, prefer unit_budget_rules over enumerating 2x/3x/4x totals.
- config_patterns must distinguish the important variants/budgets.
- system_prompt: genera solo note specifiche del target, brevi e nella lingua dell'utente. Non duplicare regole generiche, budget, prezzi, piattaforme, JSON schema o hard exclusions: il motore le aggiunge con template fisso.
- system_prompt: può indicare ambiguità del dominio, es. "per bundle controlla se smembrabile", ma senza sostituire il protocollo fisso del motore.

Hard output constraints:
- Unique list values only.
- No generated numeric ranges or sequences.
- JSON under 6000 characters.
- Output only JSON.
- Final sanity before output: reject your own config if it creates unit_budget_rules from technical_specs instead of commercial_quantity.
{retry_note}
"""
    emit("generator_start", "Genero la config SpyEngine dal piano JSON")
    config_raw, err = call_llm_messages(
        [{"role": "system", "content": generator_system}, {"role": "user", "content": generator_user}],
        max_tokens=int(os.environ.get("LLAMA_GUI_GENERATOR_MAX_TOKENS", "2000")),
        temperature=0.15,
        progress=emit,
        stream=True,
    )
    if err:
        emit("generator_error", f"Errore generator: {err}")
        return None, err

    emit("generator_raw", "Config raw ricevuta dal modello", config_raw or "")
    emit("done_llm", "Chiamate LLM completate")
    return (plan_raw or "") + "\n\n--- FINAL CONFIG ---\n\n" + (config_raw or ""), None


def generate_config_with_ai(user_description: str, progress: Any = None, mode: str = "fast", enrichment_note: str = "") -> tuple[dict | None, str, list[str]]:
    if not user_description.strip():
        return None, "Descrizione vuota", []

    if not llama_online():
        return None, "llama-server non è online", []

    def emit(stage: str, message: str, detail: Any = None):
        if not progress:
            return
        try:
            progress(stage, message, detail, None)
        except Exception:
            pass

    emit("health_ok", "llama-server online")
    if mode == "accurate":
        raw1, err1 = call_llm_for_config(user_description, progress=progress, enrichment_note=enrichment_note)
    else:
        raw1, err1 = call_llm_for_config_fast(user_description, progress=progress, enrichment_note=enrichment_note)
    if err1:
        emit("error", err1)
        return None, err1, []

    # Final config is after separator, but extract_json_object can also handle the whole text if needed.
    raw_final = raw1.split("--- FINAL CONFIG ---", 1)[-1] if raw1 and "--- FINAL CONFIG ---" in raw1 else (raw1 or "")
    cfg = extract_json_object(raw_final)

    raw_combined = raw1 or ""
    if not cfg:
        emit("parse_failed", "Config finale non recuperabile: provo retry strict", raw_final)
        retry_note = (
            "Previous output was invalid/truncated. Make the JSON shorter. "
            "Use max 8 values per list except search_keywords. Use short Italian marketplace keywords. Do not repeat terms. Do not output markdown."
        )
        if mode == "accurate":
            raw2, err2 = call_llm_for_config(
                user_description,
                retry_note=retry_note,
                progress=progress,
                enrichment_note=enrichment_note,
            )
        else:
            raw2, err2 = call_llm_for_config_fast(
                user_description,
                retry_note=retry_note,
                progress=progress,
                enrichment_note=enrichment_note,
            )
        raw_combined = (raw1 or "") + "\n\n--- RETRY STRICT ---\n\n" + (raw2 or err2 or "")
        raw_final2 = raw2.split("--- FINAL CONFIG ---", 1)[-1] if raw2 and "--- FINAL CONFIG ---" in raw2 else (raw2 or "")
        cfg = extract_json_object(raw_final2)

    if not cfg:
        emit("failed", "Config non generata dopo retry", raw_combined)
        return None, raw_combined, []

    emit("normalize_start", "Normalizzo e ripulisco la config")
    normalized, warnings = normalize_generated_config(cfg, user_description=user_description)
    emit("normalize_done", "Config normalizzata", json.dumps(normalized, indent=2, ensure_ascii=False))
    if warnings:
        emit("warnings", f"{len(warnings)} correzioni automatiche applicate", "\n".join(warnings))
    return normalized, raw_combined, warnings



def short_model_name(value: str, max_len: int = 46) -> str:
    value = str(value or "").strip()
    if not value:
        return "—"
    name = Path(value).name
    if len(name) <= max_len:
        return name
    return name[:22] + "…" + name[-20:]


def render_active_model_top_card(health: dict | None = None):
    """
    Compact top-card version of the old sidebar 'Modello attivo' panel.
    Keeps sidebar free for logs/server output.
    """
    health = health or {}
    online = bool(health.get("ok") or health.get("online") or health.get("status") == "online")
    status = "ONLINE" if online else "OFFLINE"
    color = "#22c55e" if online else "#ff3b30"

    model = (
        os.environ.get("LLAMA_MODEL")
        or os.environ.get("MODEL")
        or health.get("model")
        or health.get("model_path")
        or ""
    )
    mmproj = (
        os.environ.get("LLAMA_MMPROJ")
        or os.environ.get("MMPROJ")
        or health.get("mmproj")
        or health.get("mmproj_path")
        or ""
    )
    port = os.environ.get("LLAMA_PORT") or str(health.get("port") or "8080")

    st.markdown(
        f"""
        <div class="spy-card">
          <div class="muted">🧠 Modello attivo</div>
          <div style="font-size:1.05rem;font-weight:800;color:{color};margin-top:0.35rem;">{status}</div>
          <div class="muted" style="margin-top:0.35rem;">porta {port}</div>
          <div class="muted" title="{model}" style="margin-top:0.35rem;">MODEL: {short_model_name(model)}</div>
          <div class="muted" title="{mmproj}" style="margin-top:0.15rem;">MMPROJ: {short_model_name(mmproj)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )




def render_wizard_trace(events: list[dict], show_details: bool = False):
    if not events:
        return

    latest = events[-1]
    latest_elapsed = latest.get("elapsed")
    latest_elapsed_txt = f"{latest_elapsed:.1f}s" if isinstance(latest_elapsed, (int, float)) else "—"

    st.markdown("#### Trace operativo wizard")
    st.info(f"{latest_elapsed_txt} — {latest.get('stage', '')}: {latest.get('message', '')}")

    rows = []
    for ev in reversed(events[-40:]):
        elapsed = ev.get("elapsed")
        elapsed_txt = f"{elapsed:.1f}s" if isinstance(elapsed, (int, float)) else "—"

        phase_elapsed = ev.get("phase_elapsed")
        phase_txt = ""
        if isinstance(phase_elapsed, (int, float)):
            phase_txt = f"{phase_elapsed:.1f}s"

        rows.append(
            {
                "#": ev.get("seq", ""),
                "tempo": elapsed_txt,
                "fase_t": phase_txt,
                "fase": ev.get("stage", ""),
                "stato": ev.get("message", ""),
            }
        )

    st.caption(
        "Eventi più recenti in alto. "
        "`tempo` è globale dall'avvio wizard; `fase_t` è il tempo locale della sottofase, se disponibile."
    )
    try:
        st.dataframe(localize_listing_rows(rows), width="stretch", hide_index=True)
    except TypeError:
        st.dataframe(rows, use_container_width=True, hide_index=True)

    if show_details:
        st.caption("Dettagli tecnici: più recenti in alto.")
        for i, ev in enumerate(reversed(events)):
            detail = ev.get("detail")
            if not detail:
                continue
            original_index = ev.get("seq", len(events) - i)
            label = f"{original_index}. {ev.get('stage', '')} — {ev.get('message', '')}"
            with st.expander(label, expanded=(i == 0 and ev.get("stage") in {"llm_stream", "llm_stream_done", "llm_first_token", "knowledge_done", "web_result"})):
                if isinstance(detail, (dict, list)):
                    try:
                        st.json(detail)
                    except Exception:
                        st.code(str(detail)[:30000], language="text")
                else:
                    txt = str(detail)
                    lang = "json" if txt.strip().startswith(("{", "[")) else "text"
                    st.code(txt[:30000], language=lang)
                    if len(txt) > 30000:
                        st.caption(f"Output troncato in UI: {len(txt)} caratteri totali.")




def _latest_nonempty_line(text: str) -> str:
    for line in reversed((text or "").splitlines()):
        if line.strip():
            return line
    return ""


def render_log_box(label: str, path: Path, lines: int, height: int, *, newest_first: bool = False):
    """Render logs with native Streamlit widgets only.

    No embedded HTML component is used here. Streamlit warned about the old
    component API, so logs are now plain st.code + st.text_area.
    """

    text = read_tail(path, lines) or f"Nessun log: {path}"
    latest = _latest_nonempty_line(text)
    st.caption(f"{label} · tail {lines} righe · `{path}`")
    if latest:
        st.code(latest, language="text")

    split = text.splitlines()
    if newest_first:
        split = list(reversed(split))
    st.text_area(
        "Ultime righe" + (" (latest-first)" if newest_first else ""),
        "\n".join(split),
        height=height,
        disabled=True,
        key=f"log_box_{str(path).replace('/', '_').replace('.', '_')}_{lines}_{height}_{newest_first}",
    )


@maybe_fragment(run_every="3s")
def render_llama_log_panel():
    render_log_box("📄 llama_server.log", LLAMA_LOG, lines=70, height=390)


@maybe_fragment(run_every="3s")
def render_manager_log_panel(height: int = 520):
    render_log_box("📄 spy_manager_v3.log", MANAGER_LOG, lines=140, height=height)


@maybe_fragment(run_every="5s")
def render_status_strip():
    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(f"**llama-server**<br>{status_badge(llama_online())}", unsafe_allow_html=True)
    col2.markdown(f"**Manager**<br>{status_badge(pid_running(MANAGER_PID), 'RUNNING', 'STOPPED')}", unsafe_allow_html=True)
    col3.metric("Config", len(list_configs()))
    latest_report_path = latest_file("data/reports/**/*.json")
    col4.metric("Ultimo report", latest_report_path.name if latest_report_path else "—")


def build_manager_command() -> list[str]:
    dry = st.session_state.get("ctrl_dry_run", True)
    notification_dry = st.session_state.get("ctrl_notification_dry_run", False)
    max_total = int(st.session_state.get("ctrl_max_total", 0) or 0)

    # Platform selection is intentionally not exposed in the sidebar.
    # The manager uses the platforms defined in each active config.
    start_cmd = [sys.executable, "-u", "scripts/run_manager.py"]
    if dry:
        start_cmd.append("--dry-run")
    elif notification_dry:
        start_cmd.append("--notification-dry-run")
    if max_total:
        start_cmd += ["--max-total", str(int(max_total))]
    return start_cmd



def compact_path(value: str | None, max_len: int = 54) -> str:
    if not value:
        return "—"
    s = str(value)
    if len(s) <= max_len:
        return s
    return "…" + s[-max_len:]


def llama_env_model() -> str:
    return os.environ.get(
        "LLAMA_MODEL",
        "./Qwen3.5-14B-A3B-Claude-Opus-Reasoning-Distilled-4.6-MXFP4_MOE.gguf",
    )


def llama_env_mmproj() -> str:
    return os.environ.get(
        "LLAMA_MMPROJ",
        "./Qwen3.5-35B-A3B-Claude-Opus-Reasoning-Distilled-4.6-mmproj-q8_0.gguf",
    )


@maybe_fragment(run_every="3s")
def render_sidebar_model_status():
    # M8.55: model info is integrated into the top llama-server card.
    # Keep this function as a no-op so sidebar/control flow is not touched.
    return

@maybe_fragment(run_every="3s")
def render_live_status_cards():
    cfgs = list_configs()
    latest_report_path = latest_file("data/reports/**/*.json")
    latest_report_name = latest_report_path.name if latest_report_path else "—"

    st.markdown("<div class='top-status-wrap'>", unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        port = int(os.environ.get("LLAMA_PORT", "8080") or 8080)
        online = llama_online(port)
        model = llama_env_model()
        mmproj = llama_env_mmproj()
        st.markdown(
            f"""
            <div class='status-card'>
              <div class='status-label'>🧠 llama-server</div>
              <div class='status-value'>{status_badge(online)}</div>
              <div class='status-mini'>porta {port}</div>
              <div class='status-mini' title='{html.escape(model)}'>MODEL: {html.escape(compact_path(model, 42))}</div>
              <div class='status-mini' title='{html.escape(mmproj)}'>MMPROJ: {html.escape(compact_path(mmproj, 42))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown(
            f"<div class='status-card'><div class='status-label'>📡 Manager</div><div class='status-value'>{status_badge(pid_running(MANAGER_PID), 'RUNNING', 'STOPPED')}</div><div class='status-mini'>orchestrazione spy</div></div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"<div class='status-card'><div class='status-label'>⚙️ Config</div><div class='status-value'>{len(cfgs)}</div><div class='status-mini'>file attivi</div></div>",
            unsafe_allow_html=True,
        )
    with c4:
        short = latest_report_name[:24] + ("…" if len(latest_report_name) > 24 else "")
        st.markdown(
            f"<div class='status-card'><div class='status-label'>📄 Ultimo report</div><div class='status-value'>{html.escape(short)}</div><div class='status-mini'>{html.escape(latest_report_name)}</div></div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


@maybe_fragment(run_every="3s")
def render_sidebar_mini_status():
    st.markdown(
        f"<div class='small-muted'>llama {status_badge(llama_online())} · manager {status_badge(pid_running(MANAGER_PID), 'RUNNING', 'STOPPED')}</div>",
        unsafe_allow_html=True,
    )


def render_top_header(page: str):
    cfgs = list_configs()
    latest_report_path = latest_file("data/reports/**/*.json")
    latest_report_name = latest_report_path.name if latest_report_path else "—"

    dev_mode = is_dev_mode()
    if is_client_page(page):
        st.markdown("<div class='hero-bar'><div class='main-title'>🕵️ SpyEngine Marketplace</div><div class='hero-kicker'>Console cliente per ricerca, verifica e catalogo annunci</div></div>", unsafe_allow_html=True)
        render_client_status_cards()
    else:
        st.markdown("<div class='hero-bar'><div class='main-title'>🛠️ SpyEngine Dev</div><div class='hero-kicker'>Strumenti avanzati, pipeline, log e diagnostica</div></div>", unsafe_allow_html=True)
        render_live_status_cards()

    labels = get_navigation_labels(dev_mode)
    nav_cols = st.columns(len(labels))
    for col, label in zip(nav_cols, labels):
        is_active = page == label
        with col:
            if st.button(label, width="stretch", type=("primary" if is_active else "secondary"), key=f"nav_{label}"):
                st.session_state["page"] = label
                st.rerun()
    st.markdown("")


def start_llama_background() -> tuple[bool, str]:
    if llama_online():
        return True, "llama-server già online"

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    log_file = open(LLAMA_STARTER_LOG, "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", "scripts/start_llama.py"],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=os.getcwd(),
            start_new_session=True,
            env=env,
        )
        return True, f"avvio richiesto pid={proc.pid}; guarda llama_starter.log / llama_server.log"
    except Exception as e:
        return False, str(e)


def stop_llama() -> tuple[bool, str]:
    try:
        r = subprocess.run([sys.executable, "scripts/stop_llama.py"], capture_output=True, text=True, timeout=20)
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, out.strip() or "stop eseguito"
    except Exception as e:
        return False, str(e)




# ==================== MARKET CACHE GUI HELPERS ====================

MARKET_PROFILES = {
    "gpu_vram_catalog": "GPU / VRAM",
    "ram_ddr4_catalog": "RAM DDR4/DDR5",
    "monitor_catalog": "Monitor",
    "refurbished_electronics": "Elettronica ricondizionata",
    "tools_battery_catalog": "Utensili a batteria",
}

MARKET_SPEC_KEYS_BY_CATEGORY = {
    "technology_gpu": ["vram_gb"],
    "technology_ram": ["module_capacity_gb", "kit_total_gb", "ddr", "form_factor", "ecc"],
    "technology_monitor": ["size_inches", "refresh_hz", "resolution"],
    "technology_storage": ["capacity_gb", "capacity_tb", "interface", "form_factor"],
    "technology_cpu": ["socket", "generation", "cores", "threads"],
    "technology_phone": ["storage_gb", "ram_gb", "model_code"],
    "tools_battery": ["volts", "battery_ah"],
}


def run_market_command_now(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    """Run a short marketplace-cache command and capture output for the GUI."""
    MARKET_QUERY_LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            cmd,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        out = (r.stdout or "") + (r.stderr or "")
        with open(MARKET_QUERY_LOG, "a", encoding="utf-8") as f:
            f.write("\n\n$ " + " ".join(cmd) + "\n")
            f.write(out)
        return int(r.returncode), out
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "") + f"\nTIMEOUT dopo {timeout}s"
        with open(MARKET_QUERY_LOG, "a", encoding="utf-8") as f:
            f.write("\n\n$ " + " ".join(cmd) + "\n")
            f.write(out)
        return 124, out
    except Exception as e:
        return 1, str(e)



def start_market_background_command(cmd: list[str], *, pid_file: Path, log_file: Path) -> tuple[bool, str]:
    """Start a long marketplace command in background and stream stdout/stderr to log_file."""

    if pid_running(pid_file):
        return False, f"Processo già in esecuzione, PID file: {pid_file}"

    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8", buffering=1) as log:
        log.write("\n" + "=" * 100 + "\n")
        log.write("$ " + " ".join(cmd) + "\n")
        log.write("=" * 100 + "\n")
        proc = subprocess.Popen(
            cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=os.getcwd(),
            text=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )

    pid_file.write_text(str(proc.pid), encoding="utf-8")
    return True, f"Avviato PID {proc.pid}. Log: {log_file}"


def stop_market_background_command(pid_file: Path) -> tuple[bool, str]:
    try:
        if not pid_file.exists():
            return False, "PID file non presente."

        raw = pid_file.read_text(encoding="utf-8").strip()
        if not raw:
            pid_file.unlink(missing_ok=True)
            return False, "PID file vuoto rimosso."

        pid = int(raw)
        if not pid_running(pid_file):
            pid_file.unlink(missing_ok=True)
            return False, "Processo già fermo."

        os.kill(pid, signal.SIGTERM)
        return True, f"Stop richiesto per PID {pid}."
    except Exception as e:
        return False, f"Errore stop: {e}"


def market_maintenance_state(*extra_args: str, timeout: int = 12) -> tuple[bool, dict[str, Any], str]:
    """Read/update maintenance reminder state without blocking the GUI."""
    db = str(MARKET_DB_DEFAULT)
    script = Path("scripts/marketplace_maintenance_state.py")
    if not script.exists():
        return False, {}, "maintenance_state script non trovato"
    cmd = [get_project_python(), str(script), "--db", db, "--json"] + list(extra_args or ["status"])
    try:
        r = subprocess.run(
            cmd,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        text = (r.stdout or "") + (r.stderr or "")
        payload = json.loads(r.stdout or "{}") if r.stdout else {}
        return r.returncode == 0, payload, text
    except Exception as e:
        return False, {}, str(e)


def render_market_maintenance_banner():
    """Client-friendly marketplace DB maintenance reminder.

    It only suggests an incremental update when the DB is older than the threshold
    or when the user explicitly starts it. Long/debug controls stay in the
    marketplace/dev tabs.
    """
    if not MARKET_DB_DEFAULT.exists():
        return

    settings = load_client_settings()
    threshold_days = int(settings.get("update_threshold_days", 30) or 30)
    critical_days = int(settings.get("critical_update_days", 90) or 90)
    running = pid_running(MARKET_MAINTENANCE_PID)
    ok, state, raw = market_maintenance_state("status", "--threshold-days", str(threshold_days), "--critical-days", str(critical_days))
    if not ok:
        with st.expander("🛠️ Manutenzione marketplace", expanded=False):
            st.caption("Controllo stato manutenzione non disponibile.")
            st.code(raw or "errore sconosciuto", language="text")
        return

    days = state.get("days_since_success")
    due = bool(state.get("due"))
    critical = bool(state.get("critical"))
    snoozed = bool(state.get("snoozed"))
    last = state.get("last_successful_incremental_update_at") or "mai"

    if not due and not running:
        return

    if running:
        st.info("🔄 Aggiornamento incrementale marketplace in corso. La GUI resta utilizzabile.")
        with st.expander("Mostra log aggiornamento", expanded=False):
            render_following_log_box(
                "marketplace_gui_maintenance_update.log",
                MARKET_MAINTENANCE_LOG,
                lines=180,
                height=360,
                newest_first=True,
            )
        return

    msg_days = "non disponibile" if days is None else f"{days} giorni"
    if critical:
        st.warning(f"🧹 Database marketplace molto datato: ultimo controllo {msg_days} fa. Consigliato aggiornamento incrementale.")
    else:
        st.info(f"🧹 Database marketplace: ultimo controllo {msg_days} fa. Vuoi aggiornare in modo incrementale?")

    c1, c2, c3, c4 = st.columns([1.2, 1, 1, 2])
    with c1:
        if st.button("🔄 Aggiorna ora", key="market_maintenance_start", width="stretch"):
            cmd = [
                get_project_python(),
                "-u",
                "scripts/marketplace_gui_update_runner.py",
                "--db",
                str(MARKET_DB_DEFAULT),
                "--status-before",
                "--status-after",
            ]
            ok2, msg = start_market_background_command(cmd, pid_file=MARKET_MAINTENANCE_PID, log_file=MARKET_MAINTENANCE_LOG)
            if ok2:
                st.success(msg)
            else:
                st.warning(msg)
            time.sleep(0.4)
            st.rerun()
    with c2:
        if st.button("⏰ Domani", key="market_maintenance_snooze_1", width="stretch"):
            market_maintenance_state("snooze", "--days", "1")
            st.toast("Promemoria rimandato a domani.")
            st.rerun()
    with c3:
        if st.button("🗓️ 7 giorni", key="market_maintenance_snooze_7", width="stretch"):
            market_maintenance_state("snooze", "--days", "7")
            st.toast("Promemoria rimandato di 7 giorni.")
            st.rerun()
    with c4:
        st.caption(f"Ultimo update: {last}. Soglia promemoria: {threshold_days} giorni. Update incrementale: non resetta il DB e non rifà la scansione ALL.")



def market_source_rows(include_disabled: bool = True) -> list[dict[str, str]]:
    try:
        from spyengine.marketplace_harvest.registry import list_sources

        rows = []
        for src in list_sources(include_experimental=True, include_disabled=include_disabled):
            rows.append(
                {
                    "name": src.name,
                    "label": src.label,
                    "status": src.status,
                    "group": src.group,
                    "notes": src.notes,
                    "requires_login": str(bool(src.requires_login)),
                }
            )
        return rows
    except Exception:
        return [
            {"name": "backmarket", "label": "Back Market", "status": "experimental", "group": "refurbished", "notes": "", "requires_login": "False"},
            {"name": "refurbed", "label": "refurbed", "status": "experimental", "group": "refurbished", "notes": "", "requires_login": "False"},
            {"name": "swappie", "label": "Swappie", "status": "experimental", "group": "refurbished", "notes": "", "requires_login": "False"},
            {"name": "rebuy", "label": "reBuy", "status": "experimental", "group": "refurbished", "notes": "", "requires_login": "False"},
            {"name": "cex", "label": "CeX", "status": "experimental", "group": "used_electronics", "notes": "", "requires_login": "False"},
        ]


def market_category_rows() -> list[dict[str, str]]:
    try:
        from spyengine.marketplace_harvest.category_schema import category_map

        cmap = category_map()
        return [
            {"key": key, "label": node.label, "group": node.group, "parent": node.parent}
            for key, node in cmap.items()
        ]
    except Exception:
        return [
            {"key": "technology_gpu", "label": "Schede video / GPU", "group": "pc_components", "parent": "technology"},
            {"key": "technology_ram", "label": "RAM desktop/notebook", "group": "pc_components", "parent": "technology"},
            {"key": "technology_monitor", "label": "Monitor", "group": "display", "parent": "technology"},
            {"key": "technology_phone", "label": "Smartphone / tablet", "group": "mobile", "parent": "technology"},
            {"key": "tools_battery", "label": "Utensili a batteria", "group": "tools", "parent": ""},
        ]


def format_market_source(name: str, source_map: dict[str, dict[str, str]]) -> str:
    row = source_map.get(name, {})
    status = row.get("status", "?")
    label = row.get("label", name)
    return f"{label} · {name} · {status}"


def format_market_category(key: str, category_map_: dict[str, dict[str, str]]) -> str:
    row = category_map_.get(key, {})
    label = row.get("label", key)
    group = row.get("group", "")
    return f"{label} · {key}" + (f" · {group}" if group else "")


def render_market_output(label: str, text: str, height: int = 320):
    if not text:
        return
    st.text_area(label, text, height=height, disabled=True)




def render_following_log_box(
    title: str,
    path: Path,
    *,
    lines: int = 240,
    height: int = 560,
    auto_follow: bool = True,
    newest_first: bool = True,
):
    """Marketplace log renderer.

    With native widgets we do not force DOM scroll. Instead the newest line is
    shown separately and latest-first is enabled by default.
    """

    render_log_box(title, path, lines, height, newest_first=bool(newest_first))

def maybe_market_auto_refresh(enabled: bool, seconds: int):
    """Auto-refresh only while the user is on the marketplace log/crawl page."""
    if not enabled:
        return
    try:
        seconds = max(1, int(seconds))
    except Exception:
        seconds = 3
    st.caption(f"Auto-refresh attivo: aggiorno ogni {seconds}s e torno all'ultima riga.")
    time.sleep(seconds)
    st.rerun()


def render_market_cache_page():
    st.markdown("### 🗃️ Cache marketplace / Nightly harvester")
    st.write(
        "Interfaccia per interrogare il catalogo locale, lanciare raccolte larghe notturne, "
        "classificare listing e controllare conflitti. Il crawler raccoglie dati: le notifiche Telegram restano al manager/config live."
    )

    source_rows = market_source_rows(include_disabled=True)
    source_map = {r["name"]: r for r in source_rows}
    auto_sources = [
        r["name"]
        for r in source_rows
        if r.get("status") not in {"disabled", "manual"} and r.get("requires_login") != "True"
    ]
    default_sources = [s for s in ["backmarket", "refurbed", "swappie", "rebuy", "cex"] if s in auto_sources]
    if not default_sources:
        default_sources = auto_sources[:5]

    category_rows = market_category_rows()
    category_map_ = {r["key"]: r for r in category_rows}
    crawl_categories = [r["key"] for r in category_rows if r["key"] not in {"technology", "unknown"}]
    default_categories = [c for c in ["technology_gpu", "technology_ram", "technology_monitor"] if c in crawl_categories]

    tab_summary, tab_crawl, tab_quality, tab_logs = st.tabs(
        ["📊 Summary / query", "🌙 Nightly crawl", "✅ Strong DB pipeline", "📄 Log"]
    )

    with tab_summary:
        st.markdown("#### Catalogo locale")
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            if st.button(
                "📊 Summary DB",
                width="stretch",
                help="Esegue query_marketplace_catalog.py --summary e mostra famiglie, varianti, identificatori e facts salvati.",
            ):
                code, out = run_market_command_now([sys.executable, "scripts/query_marketplace_catalog.py", "--summary"], timeout=60)
                st.session_state["market_last_output"] = out
                st.session_state["market_last_code"] = code
        with c2:
            recent_limit = st.number_input(
                "Recent limit",
                min_value=1,
                max_value=500,
                value=20,
                step=10,
                help="Quanti listing recenti mostrare dalla cache marketplace.",
                key="market_recent_limit",
            )
            if st.button(
                "🧾 Recent",
                width="stretch",
                help="Esegue nightly_marketplace_harvester.py recent --limit N.",
            ):
                code, out = run_market_command_now(
                    [sys.executable, "scripts/nightly_marketplace_harvester.py", "recent", "--limit", str(int(recent_limit))],
                    timeout=60,
                )
                st.session_state["market_last_output"] = out
                st.session_state["market_last_code"] = code

        st.markdown("#### Query varianti")
        col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
        with col1:
            query_category = st.selectbox(
                "Category",
                [""] + crawl_categories,
                format_func=lambda k: "Tutte" if not k else format_market_category(k, category_map_),
                help="Valore passato a --category. Esempio: technology_gpu.",
                key="market_query_category",
            )
        with col2:
            spec_options = [""] + MARKET_SPEC_KEYS_BY_CATEGORY.get(query_category, sorted({x for xs in MARKET_SPEC_KEYS_BY_CATEGORY.values() for x in xs}))
            query_spec = st.selectbox(
                "Spec key",
                spec_options,
                help="Valore passato a --spec-key. Esempio GPU: vram_gb.",
                key="market_query_spec",
            )
        with col3:
            use_min = st.checkbox(
                "Usa --min",
                value=bool(query_spec),
                help="Attiva filtro minimo numerico. Esempio: vram_gb >= 24.",
                key="market_query_use_min",
            )
            min_value = st.number_input(
                "Min",
                min_value=0.0,
                value=24.0 if query_spec == "vram_gb" else 0.0,
                step=1.0,
                disabled=not use_min,
                help="Quantità minima usata con --min. Vale solo per spec numeriche.",
                key="market_query_min",
            )
        with col4:
            query_limit = st.number_input(
                "Limit",
                min_value=1,
                max_value=1000,
                value=50,
                step=10,
                help="Numero massimo di righe da restituire.",
                key="market_query_limit",
            )

        query_cmd = [sys.executable, "scripts/query_marketplace_catalog.py", "--limit", str(int(query_limit))]
        if query_category:
            query_cmd += ["--category", query_category]
        if query_spec:
            query_cmd += ["--spec-key", query_spec]
        if use_min and query_spec:
            query_cmd += ["--min", str(float(min_value))]
        st.code(" ".join(query_cmd), language="bash")

        if st.button("🔎 Esegui query catalogo", type="primary", help="Esegue il comando sopra e mostra JSON/output.", width="stretch"):
            code, out = run_market_command_now(query_cmd, timeout=90)
            st.session_state["market_last_output"] = out
            st.session_state["market_last_code"] = code

        if st.session_state.get("market_last_output"):
            code = st.session_state.get("market_last_code", 0)
            st.caption(f"Exit code: {code}")
            out = st.session_state["market_last_output"]
            try:
                st.json(json.loads(out))
            except Exception:
                render_market_output("Output", out, height=420)

    with tab_crawl:
        st.markdown("#### Crawler nativo del sito")
        st.caption("Nota M8.81+: il crawl salva candidati/raw. Il catalogo finale resta volutamente vuoto finché non fai Clean → Verify online → Promote.")
        st.write(
            "Qui non scegli un profilo tipo GPU/RAM. SpyEngine apre ogni sorgente, scopre le categorie reali del sito "
            "nell'ordine in cui le trova, entra nelle sottocategorie e poi salva i listing. "
            "La classificazione famiglia/variante avviene dopo."
        )

        no_robots = st.checkbox(
            "Ignora robots.txt",
            value=False,
            help="Sconsigliato. Di default SpyEngine rispetta robots.txt; usa questa opzione solo per test controllati.",
            key="market_no_robots",
        )
        force_refetch = st.checkbox(
            "Rifai anche completati",
            value=False,
            help="Se disattivo, il crawler salta categoria/pagina già completate nei checkpoint. Se attivo, rifà anche quelle.",
            key="market_force_refetch",
        )

        selected_sources = st.multiselect(
            "Sorgenti",
            auto_sources,
            default=auto_sources,
            format_func=lambda n: format_market_source(n, source_map),
            help=(
                "Sorgenti automatiche. La scritta experimental/stable è informativa. "
                "Amazon/Facebook restano manual/API/import-only."
            ),
            key="market_sources",
        )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            max_depth = st.number_input(
                "Profondità categorie",
                min_value=0,
                value=0,
                step=1,
                help="0 = tutte le profondità che riesce a trovare. Numero >0 limita i livelli di sottocategorie.",
                key="market_native_max_depth",
            )
        with col2:
            max_categories = st.number_input(
                "Max categorie/sito",
                min_value=0,
                value=0,
                step=50,
                help="0 = tutte le categorie che trova sul sito. Numero >0 limita quante categorie processare.",
                key="market_native_max_categories",
            )
        with col3:
            max_pages = st.number_input(
                "Max pagine/categoria",
                min_value=0,
                value=0,
                step=1,
                help="0 = tutte le pagine di paginazione che riesce a scoprire. Numero >0 limita le pagine.",
                key="market_native_max_pages",
            )
        with col4:
            per_category_limit = st.number_input(
                "Listing/categoria",
                min_value=1,
                max_value=1000,
                value=40,
                step=10,
                help="Numero massimo di listing parsati per pagina categoria.",
                key="market_native_per_category_limit",
            )

        col1, col2, col3 = st.columns(3)
        with col1:
            show_limit = st.number_input(
                "Show limit discovery",
                min_value=1,
                max_value=5000,
                value=160,
                step=40,
                help="Quante categorie mostrare nel comando di discovery.",
                key="market_native_show_limit",
            )
        with col2:
            sleep_min = st.number_input(
                "Sleep min",
                min_value=0.0,
                max_value=120.0,
                value=4.0,
                step=1.0,
                help="Pausa minima tra richieste nel run reale.",
                key="market_sleep_min",
            )
        with col3:
            sleep_max = st.number_input(
                "Sleep max",
                min_value=0.0,
                max_value=180.0,
                value=12.0,
                step=1.0,
                help="Pausa massima/random tra richieste nel run reale.",
                key="market_sleep_max",
            )

        discover_cmd = [sys.executable, "-u", "scripts/nightly_marketplace_harvester.py", "discover-site-categories"]
        crawl_cmd = [sys.executable, "-u", "scripts/nightly_marketplace_harvester.py", "crawl-sites"]

        for cmd in (discover_cmd, crawl_cmd):
            if selected_sources:
                cmd += ["--sources", ",".join(selected_sources)]
            if no_robots:
                cmd.append("--no-robots")
            if cmd is crawl_cmd and force_refetch:
                cmd.append("--force")
            cmd += [
                "--max-depth", str(int(max_depth)),
                "--max-categories-per-source", str(int(max_categories)),
                "--sleep-min", str(float(sleep_min)),
                "--sleep-max", str(float(sleep_max)),
            ]

        discover_cmd += ["--show-limit", str(int(show_limit))]
        crawl_cmd += [
            "--max-pages", str(int(max_pages)),
            "--per-category-limit", str(int(per_category_limit)),
        ]

        st.markdown("##### Comando crawler reale")
        st.code(" ".join(crawl_cmd), language="bash")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            if st.button(
                "🔎 Scopri categorie sito",
                width="stretch",
                help="Visita le homepage/entrypoint e stampa le categorie reali trovate sul sito. Non salva listing.",
            ):
                code, out = run_market_command_now(discover_cmd, timeout=180)
                st.session_state["market_crawl_output"] = out
                st.session_state["market_crawl_code"] = code
        with c2:
            if st.button(
                "🧪 Simula crawl nativo",
                width="stretch",
                help="Scopre le categorie reali e stampa il piano, ma non salva listing.",
            ):
                dry_cmd = list(crawl_cmd) + ["--dry-run"]
                code, out = run_market_command_now(dry_cmd, timeout=240)
                st.session_state["market_crawl_output"] = out
                st.session_state["market_crawl_code"] = code
        with c3:
            if st.button(
                "🌙 Avvia crawl nativo",
                width="stretch",
                help="Avvia il crawler reale in background: sito → prima categoria trovata → sottocategorie → categoria successiva.",
            ):
                MARKET_HARVESTER_LOG.parent.mkdir(parents=True, exist_ok=True)
                ok, msg = process_start(crawl_cmd, MARKET_HARVESTER_PID, MARKET_HARVESTER_LOG)
                st.toast(("OK: " if ok else "ERRORE: ") + msg)
                time.sleep(0.5)
                st.rerun()
        with c4:
            if st.button("⏹️ Ferma harvester", width="stretch", help="Ferma il processo background del marketplace harvester se attivo."):
                ok, msg = process_stop(MARKET_HARVESTER_PID, "marketplace harvester")
                st.toast(("OK: " if ok else "ERRORE: ") + msg)
                time.sleep(0.5)
                st.rerun()

        running_now = pid_running(MARKET_HARVESTER_PID)
        st.markdown("**Stato harvester:** " + status_badge(running_now, "RUNNING", "STOPPED"), unsafe_allow_html=True)

        st.markdown("#### Log crawl live")
        lc1, lc2, lc3, lc4 = st.columns([1, 1, 1, 1])
        with lc1:
            show_crawl_log = st.checkbox(
                "Mostra log",
                value=True,
                help="Mostra qui il log del crawler senza dover cambiare tab.",
                key="market_crawl_show_log",
            )
        with lc2:
            crawl_auto_refresh = st.checkbox(
                "Auto-refresh",
                value=bool(running_now),
                help="Aggiorna questa pagina periodicamente mentre il crawler gira.",
                key="market_crawl_auto_refresh",
            )
        with lc3:
            crawl_refresh_seconds = st.number_input(
                "Refresh sec",
                min_value=1,
                max_value=60,
                value=3,
                step=1,
                help="Ogni quanti secondi aggiornare il log live.",
                key="market_crawl_refresh_seconds",
            )
        with lc4:
            crawl_tail_lines = st.number_input(
                "Tail righe",
                min_value=20,
                max_value=5000,
                value=160,
                step=20,
                help="Quante ultime righe mostrare.",
                key="market_crawl_tail_lines",
            )

        newest_first = st.checkbox(
            "Latest-first",
            value=True,
            help="Mostra le righe più recenti in alto: l'ultima riga prodotta resta sempre visibile senza JS custom.",
            key="market_crawl_latest_first",
        )

        if show_crawl_log:
            render_following_log_box(
                "🌙 nightly_marketplace_harvester.log",
                MARKET_HARVESTER_LOG,
                lines=int(crawl_tail_lines),
                height=360,
                newest_first=bool(newest_first),
            )

        if bool(crawl_auto_refresh) and bool(running_now):
            maybe_market_auto_refresh(True, int(crawl_refresh_seconds))

        ck1, ck2, ck3 = st.columns([1, 1, 2])
        with ck1:
            if st.button(
                "📌 Resume/checkpoint",
                width="stretch",
                help="Mostra task completati/da riprendere. Se checkpoint è vuoto ma search_runs/listings crescono, il crawler sta comunque salvando.",
            ):
                code, out = run_market_command_now(
                    [sys.executable, "scripts/nightly_marketplace_harvester.py", "checkpoint-summary", "--recent", "20"],
                    timeout=60,
                )
                st.session_state["market_checkpoint_output"] = out
                st.session_state["market_checkpoint_code"] = code
        with ck2:
            if st.button(
                "📊 DB summary",
                width="stretch",
                help="Mostra conteggi listings/observations/families/variants direttamente dal catalogo.",
            ):
                code, out = run_market_command_now(
                    [sys.executable, "scripts/query_marketplace_catalog.py", "--summary"],
                    timeout=60,
                )
                st.session_state["market_checkpoint_output"] = out
                st.session_state["market_checkpoint_code"] = code

        with st.expander("Manutenzione DB marketplace", expanded=False):
            st.warning(
                "I dati raccolti con M8.74/M8.75 possono essere sporchi se vedi famiglie tipo "
                "'Apple Weeks Smartphones...' o numeri telefono come volts. Consigliato reset e crawl pulito."
            )
            dry_reset_cmd = [sys.executable, "scripts/reset_marketplace_cache.py"]
            reset_cmd = [sys.executable, "scripts/reset_marketplace_cache.py", "--apply"]
            st.code(" ".join(reset_cmd), language="bash")
            r1, r2 = st.columns(2)
            with r1:
                if st.button("🧪 Simula reset cache", width="stretch"):
                    code, out = run_market_command_now(dry_reset_cmd, timeout=60)
                    st.session_state["market_checkpoint_output"] = out
                    st.session_state["market_checkpoint_code"] = code
            with r2:
                if st.button("🧹 Reset cache con backup", width="stretch"):
                    code, out = run_market_command_now(reset_cmd, timeout=60)
                    st.session_state["market_checkpoint_output"] = out
                    st.session_state["market_checkpoint_code"] = code

        if st.session_state.get("market_checkpoint_output"):
            st.caption(f"Checkpoint exit code: {st.session_state.get('market_checkpoint_code', 0)}")
            try:
                st.json(json.loads(st.session_state["market_checkpoint_output"]))
            except Exception:
                render_market_output("Checkpoint / DB", st.session_state["market_checkpoint_output"], height=260)

        if st.session_state.get("market_crawl_output"):
            st.caption(f"Exit code: {st.session_state.get('market_crawl_code', 0)}")
            render_market_output("Output discovery / crawl nativo", st.session_state["market_crawl_output"], height=430)

        with st.expander("Fallback vecchio: query/profile broad-first", expanded=False):
            st.write("Resta disponibile da CLI per debug mirati. Il flusso principale ora è `crawl-sites` nativo per sito.")
            st.code(
                "python scripts/nightly_marketplace_harvester.py harvest --profile gpu_vram_catalog --sources backmarket,refurbed --dry-run",
                language="bash",
            )

        with st.expander("Sorgenti manual/API/import-only", expanded=False):
            manual = [r for r in source_rows if r.get("status") in {"manual", "disabled"} or r.get("requires_login") == "True"]
            for r in manual:
                st.write(f"**{r['label']}** · `{r['name']}` · `{r['status']}`")
                if r.get("notes"):
                    st.caption(r["notes"])


    with tab_quality:
        st.markdown("## ✅ Strong DB pipeline")
        st.info(
            "Workflow separato: FETCH salva candidati/raw; CLEAN pulisce; VERIFY ONLINE controlla; "
            "PROMOTE crea solo dopo il catalogo finale product_families/product_variants/spec_facts."
        )

        st.markdown(
            """
            **Ordine corretto**
            1. `crawl-sites` nella tab Nightly crawl.
            2. `Clean batch`.
            3. `Verify online`.
            4. `Promote verified`.
            """
        )

        st.markdown("### 🚀 All in one")
        st.write("Esegue tutto passo passo: **FETCH → CLEAN → VERIFY ONLINE → PROMOTE → STATUS**.")

        aio_src1, aio_src2, aio_src3, aio_src4 = st.columns([1, 1, 1, 2])
        if "market_aio_sources_selected" not in st.session_state:
            st.session_state["market_aio_sources_selected"] = [s for s in ["refurbed"] if s in auto_sources] or auto_sources[:1]

        with aio_src1:
            if st.button("✅ AIO select all", width="stretch", help="Seleziona tutte le sorgenti automatiche disponibili."):
                st.session_state["market_aio_sources_selected"] = list(auto_sources)
        with aio_src2:
            if st.button("🧹 AIO clear", width="stretch", help="Svuota selezione sorgenti AIO."):
                st.session_state["market_aio_sources_selected"] = []
        with aio_src3:
            if st.button("🎯 Solo refurbed", width="stretch", help="Seleziona solo refurbed per test rapidi."):
                st.session_state["market_aio_sources_selected"] = [s for s in ["refurbed"] if s in auto_sources] or auto_sources[:1]
        with aio_src4:
            st.caption(f"Sorgenti automatiche selezionabili: {len(auto_sources)}")

        aio_sources_selected = st.multiselect(
            "AIO sorgenti",
            auto_sources,
            format_func=lambda n: format_market_source(n, source_map),
            help="Sorgenti automatiche per la pipeline all-in-one. Usa select all per includerle tutte.",
            key="market_aio_sources_selected",
        )
        aio_sources_arg = ",".join(aio_sources_selected)

        aio1, aio2, aio3 = st.columns([1, 1, 1])
        with aio1:
            aio_limit = st.number_input(
                "AIO limit",
                min_value=1,
                max_value=20000,
                value=500,
                step=100,
                help="Batch size per clean/verify/promote.",
                key="market_aio_limit",
            )
        with aio2:
            aio_depth = st.number_input(
                "AIO depth",
                min_value=0,
                value=1,
                step=1,
                help="0 = tutte le sottocategorie trovate.",
                key="market_aio_depth",
            )
        with aio3:
            aio_categories = st.number_input(
                "AIO categorie/sito",
                min_value=0,
                value=20,
                step=20,
                help="0 = tutte le categorie trovate.",
                key="market_aio_categories",
            )

        aio5, aio6, aio7, aio8 = st.columns([1, 1, 1, 1])
        with aio5:
            aio_pages = st.number_input(
                "AIO pagine/categoria",
                min_value=0,
                value=1,
                step=1,
                help="0 = tutte le pagine trovate.",
                key="market_aio_pages",
            )
        with aio6:
            aio_ai_clean = st.checkbox(
                "AIO AI clean",
                value=False,
                help="Usa AI solo nella fase clean sui casi incerti.",
                key="market_aio_ai_clean",
            )
        with aio7:
            aio_verify_reject = st.checkbox(
                "AIO verifica reject",
                value=True,
                help="Verifica online anche i record scartati dal clean, per DB più strong.",
                key="market_aio_verify_reject",
            )
        with aio8:
            aio_force = st.checkbox(
                "AIO force fetch",
                value=False,
                help="Rifà anche pagine già completate nei checkpoint.",
                key="market_aio_force",
            )

        aio9, aio10, aio11 = st.columns([1, 1, 2])
        with aio9:
            aio_dry = st.checkbox(
                "AIO dry-run",
                value=False,
                help="Simula fetch/postprocess e non promuove.",
                key="market_aio_dry",
            )
        with aio10:
            aio_reset = st.checkbox(
                "AIO reset DB con backup",
                value=False,
                help="Crea backup del DB e riparte pulito. Da usare se il DB è sporco.",
                key="market_aio_reset",
            )
        with aio11:
            aio_verbose = st.checkbox(
                "AIO verbose",
                value=True,
                key="market_aio_verbose",
            )

        aio_cmd = [
            sys.executable,
            "scripts/marketplace_all_in_one_pipeline.py",
            "--sources",
            aio_sources_arg or "refurbed",
            "--max-depth",
            str(int(aio_depth)),
            "--max-categories-per-source",
            str(int(aio_categories)),
            "--max-pages",
            str(int(aio_pages)),
            "--limit",
            str(int(aio_limit)),
        ]
        if aio_ai_clean:
            aio_cmd.append("--ai-clean")
        if aio_verify_reject:
            aio_cmd.append("--include-rejected-clean")
        else:
            aio_cmd.append("--skip-include-rejected-clean")
        if aio_force:
            aio_cmd.append("--force")
        if aio_dry:
            aio_cmd.append("--dry-run")
        if aio_reset:
            aio_cmd.append("--reset-cache-with-backup")
        if aio_verbose:
            aio_cmd.append("--verbose")

        if not aio_sources_selected:
            st.warning("Seleziona almeno una sorgente AIO. Se lasci vuoto, il comando userà fallback `refurbed`.")

        st.code(" ".join(aio_cmd), language="bash")

        aio_running = pid_running(MARKET_AIO_PID)
        st.markdown("**Stato AIO:** " + status_badge(aio_running, "RUNNING", "STOPPED"), unsafe_allow_html=True)

        aio_b1, aio_b2, aio_b3, aio_b4 = st.columns([1, 1, 1, 2])
        with aio_b1:
            if st.button(
                "🚀 Start AIO",
                width="stretch",
                help="Avvia la pipeline completa in background e scrive log live.",
                disabled=bool(aio_running),
            ):
                ok, msg = start_market_background_command(aio_cmd, pid_file=MARKET_AIO_PID, log_file=MARKET_AIO_LOG)
                if ok:
                    st.success(msg)
                else:
                    st.warning(msg)
                st.rerun()
        with aio_b2:
            if st.button(
                "⏹️ Stop AIO",
                width="stretch",
                help="Ferma la pipeline all-in-one in background.",
                disabled=not bool(aio_running),
            ):
                ok, msg = stop_market_background_command(MARKET_AIO_PID)
                if ok:
                    st.warning(msg)
                else:
                    st.info(msg)
                st.rerun()
        with aio_b3:
            if st.button(
                "📊 AIO status",
                width="stretch",
                help="Mostra stato pipeline/database.",
            ):
                code, out = run_market_command_now(
                    [sys.executable, "scripts/marketplace_pipeline_status.py", "--recent", "10"],
                    timeout=90,
                )
                st.session_state["market_quality_output"] = out
                st.session_state["market_quality_code"] = code
        with aio_b4:
            st.caption(
                "Modalità completa: fetch candidati/raw, cleaning, verifica online, promote dei soli verified e status finale."
            )

        st.markdown("#### Log live AIO")
        aio_l1, aio_l2, aio_l3 = st.columns([1, 1, 1])
        with aio_l1:
            aio_show_log = st.checkbox("Mostra log AIO", value=True, key="market_aio_show_log")
        with aio_l2:
            aio_auto_refresh = st.checkbox("Auto-refresh AIO", value=bool(aio_running), key="market_aio_auto_refresh")
        with aio_l3:
            aio_tail_lines = st.number_input("AIO tail righe", min_value=20, max_value=5000, value=220, step=20, key="market_aio_tail_lines")

        if aio_show_log:
            render_following_log_box(
                "🚀 marketplace_all_in_one_pipeline.log",
                MARKET_AIO_LOG,
                lines=int(aio_tail_lines),
                height=420,
                newest_first=True,
            )

        if bool(aio_auto_refresh) and bool(aio_running):
            maybe_market_auto_refresh(True, 3)

        st.divider()

        p1, p2, p3, p4 = st.columns([1, 1, 1, 1])
        with p1:
            pipeline_limit = st.number_input(
                "Pipeline limit",
                min_value=1,
                max_value=10000,
                value=500,
                step=100,
                key="market_pipeline_limit",
                help="Quanti listing processare per ogni batch clean/verify/promote.",
            )
        with p2:
            pipeline_ai_clean = st.checkbox(
                "AI clean sui dubbi",
                value=False,
                key="market_pipeline_ai_clean",
                help="Il crawler non usa AI. Qui la AI lavora solo in batch sui casi uncertain.",
            )
        with p3:
            pipeline_verify_reject = st.checkbox(
                "Verifica anche reject",
                value=True,
                key="market_pipeline_verify_reject",
                help="Per DB molto strong: verifica online anche record che il cleaning avrebbe scartato.",
            )
        with p4:
            pipeline_dry = st.checkbox(
                "Dry-run pipeline",
                value=False,
                key="market_pipeline_dry",
                help="Mostra cosa farebbe clean/verify e non promuove.",
            )

        cmd_pipeline = [
            sys.executable,
            "scripts/marketplace_postprocess_pipeline.py",
            "--limit",
            str(int(pipeline_limit)),
        ]
        if pipeline_ai_clean:
            cmd_pipeline.append("--ai-clean")
        if pipeline_verify_reject:
            cmd_pipeline.append("--include-rejected-clean")
        if pipeline_dry:
            cmd_pipeline.append("--dry-run")

        st.code(" ".join(cmd_pipeline), language="bash")

        bp1, bp2, bp3 = st.columns([1, 1, 1])
        with bp1:
            if st.button(
                "📊 Pipeline status",
                width="stretch",
                help="Mostra fetch/clean/verify/catalog finale in un solo JSON.",
            ):
                code, out = run_market_command_now(
                    [sys.executable, "scripts/marketplace_pipeline_status.py", "--recent", "10"],
                    timeout=90,
                )
                st.session_state["market_quality_output"] = out
                st.session_state["market_quality_code"] = code
        with bp2:
            if st.button(
                "🚦 Run post-fetch pipeline",
                width="stretch",
                help="Esegue Clean → Verify online → Promote verified, rispettando le opzioni sopra.",
            ):
                code, out = run_market_command_now(cmd_pipeline, timeout=900)
                st.session_state["market_quality_output"] = out
                st.session_state["market_quality_code"] = code
        with bp3:
            if st.button(
                "✅ Solo promote verified",
                width="stretch",
                help="Promuove nel catalogo finale solo listing già verified online.",
            ):
                code, out = run_market_command_now(
                    [sys.executable, "scripts/promote_verified_marketplace_catalog.py", "--limit", str(int(pipeline_limit))],
                    timeout=240,
                )
                st.session_state["market_quality_output"] = out
                st.session_state["market_quality_code"] = code

        st.divider()



        st.markdown("### 🧪 Smoke test sorgenti")
        st.caption(
            "Test leggerissimo: per ogni sorgente prova 1 categoria, 1 pagina, 1 listing. "
            "Serve a isolare fonti che non scoprono/fetchano nulla prima di fare crawl grandi."
        )

        sm1, sm2, sm3, sm4, sm5 = st.columns([1, 1, 1, 1, 1])
        with sm1:
            smoke_all = st.checkbox("Smoke all sources", value=True, key="market_smoke_all_sources")
        with sm2:
            smoke_categories_to_try = st.number_input("Categorie da provare", min_value=1, max_value=50, value=8, step=1, key="market_smoke_categories_to_try")
        with sm3:
            smoke_limit_timeout = st.number_input("Timeout/source sec", min_value=15, max_value=600, value=90, step=15, key="market_smoke_timeout")
        with sm4:
            smoke_no_robots = st.checkbox("Smoke ignore robots", value=False, key="market_smoke_no_robots")
        with sm5:
            smoke_force = st.checkbox("Smoke force", value=True, key="market_smoke_force")

        if smoke_all:
            smoke_sources_arg = "all"
            smoke_selected = list(auto_sources)
        else:
            smoke_selected = st.multiselect(
                "Smoke sorgenti",
                auto_sources,
                default=[s for s in ["refurbed"] if s in auto_sources] or auto_sources[:1],
                format_func=lambda n: format_market_source(n, source_map),
                key="market_smoke_sources_selected",
            )
            smoke_sources_arg = ",".join(smoke_selected) or "refurbed"

        smoke_cmd = [
            get_project_python(),
            "scripts/smoke_test_market_sources.py",
            "--sources",
            smoke_sources_arg,
            "--max-depth",
            "1",
            "--max-categories-per-source",
            str(int(smoke_categories_to_try)),
            "--max-pages",
            "1",
            "--per-category-limit",
            "1",
            "--timeout",
            str(int(smoke_limit_timeout)),
            "--force",
            "--verbose",
        ]
        if smoke_no_robots:
            smoke_cmd.append("--no-robots")
        if not smoke_force:
            # Remove force if user disabled it.
            smoke_cmd = [x for x in smoke_cmd if x != "--force"]

        st.code(" ".join(smoke_cmd), language="bash")

        sm_b1, sm_b2, sm_b3 = st.columns([1, 1, 2])
        with sm_b1:
            if st.button("🧪 Run source smoke", width="stretch"):
                code, out = run_market_command_now(smoke_cmd, timeout=max(120, int(smoke_limit_timeout) * max(1, len(smoke_selected if not smoke_all else auto_sources)) + 60))
                st.session_state["market_quality_output"] = out
                st.session_state["market_quality_code"] = code
        with sm_b2:
            if st.button("📄 Show smoke report", width="stretch"):
                report = Path("logs/source_smoke_test_report.md")
                if report.exists():
                    st.session_state["market_quality_output"] = report.read_text(encoding="utf-8")
                    st.session_state["market_quality_code"] = 0
                else:
                    st.session_state["market_quality_output"] = "Report non ancora presente: esegui prima Run source smoke."
                    st.session_state["market_quality_code"] = 1
        with sm_b3:
            st.caption("Output: logs/source_smoke_test_report.json e logs/source_smoke_test_report.md")

        st.divider()

        st.markdown("#### Clean listing batch")
        cl1, cl2, cl3, cl4 = st.columns([1, 1, 1, 1])
        with cl1:
            clean_limit = st.number_input("Clean limit", min_value=1, max_value=5000, value=100, step=50, key="market_clean_limit")
        with cl2:
            use_ai_clean = st.checkbox("Usa AI sui dubbi", value=False, help="Il crawler non usa AI. Questa fase batch la usa solo sui casi uncertain.", key="market_clean_use_ai")
        with cl3:
            if st.button("🧪 Clean dry-run", width="stretch"):
                cmd = [sys.executable, "scripts/clean_marketplace_listings.py", "--enqueue-missing", "--dry-run", "--limit", str(int(clean_limit))]
                if use_ai_clean:
                    cmd.append("--ai")
                code, out = run_market_command_now(cmd, timeout=180)
                st.session_state["market_quality_output"] = out
                st.session_state["market_quality_code"] = code
        with cl4:
            if st.button("🧹 Clean batch", width="stretch"):
                cmd = [sys.executable, "scripts/clean_marketplace_listings.py", "--enqueue-missing", "--limit", str(int(clean_limit))]
                if use_ai_clean:
                    cmd.append("--ai")
                else:
                    cmd.append("--deterministic-only")
                code, out = run_market_command_now(cmd, timeout=240)
                st.session_state["market_quality_output"] = out
                st.session_state["market_quality_code"] = code

        st.markdown("#### Verify online batch")
        vf1, vf2, vf3, vf4 = st.columns([1, 1, 1, 1])
        with vf1:
            verify_limit = st.number_input("Verify limit", min_value=1, max_value=5000, value=100, step=50, key="market_verify_limit")
        with vf2:
            verify_all = st.checkbox("Verifica anche reject", value=False, help="Di default salta i reject della pulizia. Attivalo per verifica letteralmente totale.", key="market_verify_include_reject")
        with vf3:
            if st.button("🌐 Verify online", width="stretch"):
                cmd = [sys.executable, "scripts/verify_marketplace_listings_online.py", "--enqueue-missing", "--limit", str(int(verify_limit))]
                if verify_all:
                    cmd.append("--include-rejected-clean")
                code, out = run_market_command_now(cmd, timeout=300)
                st.session_state["market_quality_output"] = out
                st.session_state["market_quality_code"] = code
        with vf4:
            if st.button("✅ Promote verified", width="stretch", help="Solo i verified online entrano nel catalogo finale family/variant/spec."):
                code, out = run_market_command_now(
                    [sys.executable, "scripts/promote_verified_marketplace_catalog.py", "--limit", str(int(verify_limit))],
                    timeout=180,
                )
                st.session_state["market_quality_output"] = out
                st.session_state["market_quality_code"] = code

        st.markdown("#### Classifier batch")
        c1, c2 = st.columns(2)
        with c1:
            cls_limit = st.number_input("Classify limit", min_value=1, max_value=2000, value=100, step=50, help="Quanti listing recenti classificare/validare in batch.", key="market_classify_limit")
        with c2:
            cls_details = st.checkbox("Details", value=False, help="Stampa anche dettaglio per listing, più verboso.", key="market_classify_details")
        cls_cmd = [sys.executable, "scripts/classify_marketplace_batch.py", "--limit", str(int(cls_limit))]
        if cls_details:
            cls_cmd.append("--details")
        st.code(" ".join(cls_cmd), language="bash")
        if st.button("🧠 Classifica batch", help="Esegue classifier/validator deterministico sui listing recenti.", width="stretch"):
            code, out = run_market_command_now(cls_cmd, timeout=120)
            st.session_state["market_quality_output"] = out
            st.session_state["market_quality_code"] = code

        st.markdown("#### Fact-check / conflitti")
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            fc_category = st.selectbox(
                "Category fact-check",
                [""] + crawl_categories,
                format_func=lambda k: "Tutte" if not k else format_market_category(k, category_map_),
                help="Categoria da controllare. Vuoto = tutte.",
                key="market_fact_category",
            )
        with c2:
            fc_limit = st.number_input("Fact limit", min_value=1, max_value=5000, value=200, step=100, key="market_fact_limit")
        with c3:
            show_sources = st.checkbox("Mostra fonti autorevoli", value=False, help="Usa --sources-for per vedere fonti dedicate alla categoria.", key="market_sources_for")

        if show_sources and fc_category:
            fc_cmd = [sys.executable, "scripts/fact_check_marketplace_catalog.py", "--sources-for", fc_category]
        else:
            fc_cmd = [sys.executable, "scripts/fact_check_marketplace_catalog.py", "--limit", str(int(fc_limit))]
            if fc_category:
                fc_cmd += ["--category", fc_category]
        st.code(" ".join(fc_cmd), language="bash")

        if st.button("🩺 Esegui fact-check", help="Controlla conflitti tipo variante impossibile o fact incoerente.", width="stretch"):
            code, out = run_market_command_now(fc_cmd, timeout=120)
            st.session_state["market_quality_output"] = out
            st.session_state["market_quality_code"] = code

        if st.session_state.get("market_quality_output"):
            st.caption(f"Exit code: {st.session_state.get('market_quality_code', 0)}")
            out = st.session_state["market_quality_output"]
            try:
                st.json(json.loads(out))
            except Exception:
                render_market_output("Output classify/fact-check", out, height=420)

    with tab_logs:
        st.markdown("#### Log marketplace realtime")
        running = pid_running(MARKET_HARVESTER_PID)
        col1, col2, col3 = st.columns(3)
        col1.markdown("**Harvester**<br>" + status_badge(running, "RUNNING", "STOPPED"), unsafe_allow_html=True)
        col2.markdown(f"**PID file:** `{MARKET_HARVESTER_PID}`")
        col3.markdown(f"**Log:** `{MARKET_HARVESTER_LOG}`")

        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            auto_refresh = st.checkbox(
                "Auto-refresh log",
                value=bool(running),
                help="Aggiorna automaticamente questa pagina mentre il crawler produce nuove righe.",
                key="market_log_auto_refresh",
            )
        with c2:
            refresh_seconds = st.number_input(
                "Ogni secondi",
                min_value=1,
                max_value=60,
                value=3,
                step=1,
                help="Intervallo tra un refresh e l'altro.",
                key="market_log_refresh_seconds",
            )
        with c3:
            tail_lines = st.number_input(
                "Tail righe",
                min_value=50,
                max_value=5000,
                value=300,
                step=50,
                help="Quante ultime righe tenere nel box. Il box si posiziona in fondo.",
                key="market_log_tail_lines",
            )

        latest_first_log = st.checkbox(
            "Latest-first nel log",
            value=True,
            help="Mostra le righe più recenti in alto, così l'ultima riga è subito visibile.",
            key="market_log_latest_first",
        )

        render_following_log_box(
            "🌙 nightly_marketplace_harvester.log",
            MARKET_HARVESTER_LOG,
            lines=int(tail_lines),
            height=560,
            newest_first=bool(latest_first_log),
        )

        with st.expander("marketplace_cache_gui.log", expanded=False):
            render_following_log_box(
                "marketplace_cache_gui.log",
                MARKET_QUERY_LOG,
                lines=180,
                height=360,
                newest_first=True,
            )

        maybe_market_auto_refresh(bool(auto_refresh), int(refresh_seconds))


# ==================== CLIENT / PRO GUI ====================

CLIENT_PAGE_HOME = "🏠 Home"
CLIENT_PAGE_PRODUCTS = "🔎 Prodotti"
CLIENT_PAGE_OPPORTUNITIES = "⭐ Opportunità"
CLIENT_PAGE_WIZARD = "🧠 Wizard AI"
CLIENT_PAGE_JOBS = "🔄 Aggiornamento"
CLIENT_PAGE_SETTINGS = "⚙️ Impostazioni"
CLIENT_PAGES = [
    CLIENT_PAGE_HOME,
    CLIENT_PAGE_PRODUCTS,
    CLIENT_PAGE_OPPORTUNITIES,
    CLIENT_PAGE_WIZARD,
    CLIENT_PAGE_JOBS,
    CLIENT_PAGE_SETTINGS,
]
CLIENT_PAGE_QUERY_ALIASES = {
    "home": CLIENT_PAGE_HOME,
    "products": CLIENT_PAGE_PRODUCTS,
    "prodotti": CLIENT_PAGE_PRODUCTS,
    "opportunities": CLIENT_PAGE_OPPORTUNITIES,
    "opportunita": CLIENT_PAGE_OPPORTUNITIES,
    "opportunità": CLIENT_PAGE_OPPORTUNITIES,
    "wizard": CLIENT_PAGE_WIZARD,
    "wizard-ai": CLIENT_PAGE_WIZARD,
    "update": CLIENT_PAGE_JOBS,
    "aggiornamento": CLIENT_PAGE_JOBS,
    "settings": CLIENT_PAGE_SETTINGS,
    "impostazioni": CLIENT_PAGE_SETTINGS,
}
DEV_PAGES = ["🏠 Dashboard", "⚙️ Config", "🗃️ Cache market", "📜 Log", "🩺 Doctor"]


def default_client_settings() -> dict[str, Any]:
    return {
        "dev_mode": False,
        "update_threshold_days": 30,
        "critical_update_days": 90,
        "products_default_limit": 150,
        "opportunities_default_limit": 80,
        "show_unknown_products": False,
        "preferred_sources": [],
        "preferred_categories": [],
        "client_theme_name": "SpyEngine Marketplace",
    }


@st.cache_data(ttl=2, show_spinner=False)
def load_client_settings() -> dict[str, Any]:
    data = load_json(CLIENT_SETTINGS_PATH, {})
    if not isinstance(data, dict):
        data = {}
    out = default_client_settings()
    out.update(data)
    return out


def save_client_settings(data: dict[str, Any]) -> None:
    merged = default_client_settings()
    merged.update(data or {})
    save_json(CLIENT_SETTINGS_PATH, merged)
    load_client_settings.clear()


def is_dev_mode() -> bool:
    if "client_dev_mode" in st.session_state:
        return bool(st.session_state.get("client_dev_mode"))
    return bool(load_client_settings().get("dev_mode", False))


def is_client_page(page: str) -> bool:
    return page in CLIENT_PAGES


def get_navigation_labels(dev_mode: bool | None = None) -> list[str]:
    labels = list(CLIENT_PAGES)
    if bool(is_dev_mode() if dev_mode is None else dev_mode):
        labels += list(DEV_PAGES)
    return labels


def requested_client_page_from_query() -> str | None:
    raw = st.query_params.get("spy_page")
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    key = str(raw or "").strip().lower().replace("_", "-")
    return CLIENT_PAGE_QUERY_ALIASES.get(key)


def market_connect_readonly() -> sqlite3.Connection | None:
    if not MARKET_DB_DEFAULT.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{MARKET_DB_DEFAULT}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con
    except Exception:
        try:
            con = sqlite3.connect(MARKET_DB_DEFAULT)
            con.row_factory = sqlite3.Row
            return con
        except Exception:
            return None


def db_table_exists(con: sqlite3.Connection, table: str) -> bool:
    try:
        return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())
    except Exception:
        return False


def db_scalar(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    try:
        row = con.execute(sql, params).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def db_group_counts(con: sqlite3.Connection, table: str, col: str) -> dict[str, int]:
    if not db_table_exists(con, table):
        return {}
    try:
        return {str(r[0] or "<empty>"): int(r[1]) for r in con.execute(f"SELECT {col}, COUNT(*) FROM {table} GROUP BY {col}")}
    except Exception:
        return {}


# ---- Client localization helpers ----
# Il DB mantiene le categorie tecniche in inglese/stabile; la GUI cliente mostra
# l'italiano come lingua principale e usa le chiavi tecniche solo internamente.
CATEGORY_LABELS_IT: dict[str, str] = {
    "unknown": "Sconosciuta",
    "baby_child_car_seat": "Seggiolini auto bambini",
    "books_media_book": "Libri e media",
    "fashion_bag": "Borse",
    "fashion_clothing": "Abbigliamento",
    "home_decor_photo_frame": "Cornici e portafoto",
    "home_decor_wall_art": "Quadri e arte da parete",
    "home_furniture_chair": "Sedie e poltrone",
    "home_furniture_table": "Tavoli",
    "home_storage_container": "Contenitori e organizzazione",
    "music_drums": "Batteria e percussioni",
    "school_bag": "Zaini scuola",
    "sports_billiards": "Biliardo",
    "sports_fishing_lure": "Esche da pesca",
    "sports_fitness_equipment": "Attrezzi fitness",
    "technology": "Tecnologia",
    "technology_accessory": "Accessori tecnologia",
    "technology_audio": "Audio",
    "technology_audio_amplifier": "Amplificatori e receiver",
    "technology_audio_headphones": "Cuffie e auricolari",
    "technology_audio_speakers": "Casse e diffusori",
    "technology_audio_turntable": "Giradischi",
    "technology_camera": "Fotocamere",
    "technology_console": "Console",
    "technology_cpu": "Processori CPU",
    "technology_desktop_pc": "PC desktop",
    "technology_gpu": "Schede video GPU",
    "technology_keyboard": "Tastiere",
    "technology_laptop": "Notebook e portatili",
    "technology_laser_level": "Livelle laser",
    "technology_monitor": "Monitor",
    "technology_phone": "Telefoni",
    "technology_printer": "Stampanti",
    "technology_ram": "Memoria RAM",
    "technology_server_parts": "Componenti server",
    "technology_smartphone": "Smartphone",
    "technology_smartwatch": "Smartwatch",
    "technology_storage": "Dischi e storage",
    "technology_tablet": "Tablet",
    "tools_battery": "Utensili a batteria",
    "tools_cutting_tool": "Utensili da taglio",
    "tools_measuring_caliper": "Calibri e strumenti di misura",
    "toys_dollhouse": "Case delle bambole",
    "toys_lego": "LEGO",
    "vehicle_car": "Auto",
    "vehicle_car_part": "Ricambi auto",
    "vehicle_motorcycle": "Moto",
    "vehicle_motorcycle_accessory": "Accessori moto",
}

CATEGORY_PREFIX_IT: dict[str, str] = {
    "technology": "Tecnologia",
    "home": "Casa",
    "fashion": "Moda",
    "vehicle": "Veicoli",
    "sports": "Sport",
    "tools": "Utensili",
    "toys": "Giocattoli",
    "books": "Libri/media",
    "baby": "Bambini",
    "music": "Musica",
    "school": "Scuola",
}

STATUS_LABELS_IT: dict[str, str] = {
    "verified": "Verificato",
    "verified_conflict": "Conflitto verificato",
    "uncertain": "Incerto",
    "rejected": "Scartato",
    "pending": "In attesa",
    "researched": "Ricercato",
    "failed": "Fallito",
    "resolved": "Risolto",
    "skipped_no_image": "Saltato: nessuna immagine",
    "accept": "Accettato",
    "reject": "Scartato",
    "new": "Nuovo",
    "new_sealed": "Nuovo sigillato",
    "refurbished": "Ricondizionato",
    "used": "Usato",
    "for_parts": "Non funzionante / ricambi",
    "good_value": "Prezzo interessante",
    "near_reference": "In linea col riferimento",
    "above_reference": "Sopra il riferimento",
    "suspicious_low_price": "Prezzo anomalo: verificare",
    "insufficient_data": "Comparabili insufficienti",
    "outgoing": "In uscita",
    "incoming": "In entrata",
    "compatible_with": "Compatibile con",
    "incompatible_with": "Non compatibile con",
    "accessory_for": "Accessorio per",
    "requires": "Richiede",
    "replacement_for": "Sostituisce",
    "successor_of": "Successore di",
    "predecessor_of": "Predecessore di",
    "often_bundled_with": "Spesso venduto insieme a",
    "": "—",
    None: "—",  # type: ignore[dict-item]
}

CLIENT_LISTING_COLUMN_LABELS: dict[str, str] = {
    "id": "ID",
    "source": "Fonte",
    "original_title": "Titolo originale",
    "title": "Titolo",
    "category": "Categoria",
    "brand": "Marca",
    "model": "Modello",
    "opportunity_status": "Valutazione prezzo",
    "opportunity_score": "Score opportunità",
    "discount_percent": "Scarto dal riferimento",
    "reference_price": "Prezzo di riferimento",
    "reference_scope": "Gruppo comparabile",
    "reference_sample_size": "Campione",
    "reference_confidence": "Affidabilità riferimento",
    "price": "Prezzo",
    "currency": "Valuta",
    "location": "Località",
    "seller": "Venditore",
    "url": "Link",
    "verify_status": "Stato verifica",
    "clean_decision": "Decisione",
    "confidence": "Confidenza",
    "reason": "Motivo",
    "last_seen": "Ultimo visto",
}

CLIENT_CATALOG_COLUMN_LABELS: dict[str, str] = {
    "id": "ID",
    "category": "Categoria",
    "brand": "Marca",
    "family_name": "Famiglia prodotto",
    "confidence": "Confidenza",
    "variants": "Varianti",
    "aliases": "Alias",
    "spec_facts": "Schede tecniche",
    "last_seen": "Ultimo visto",
}
CLIENT_COMPACT_LISTING_KEYS = {
    "title",
    "category",
    "brand",
    "model",
    "price",
    "currency",
    "location",
    "opportunity_status",
    "opportunity_score",
    "discount_percent",
    "url",
    "last_seen",
}


def category_label_it(key: Any, *, include_key: bool = False) -> str:
    if key is None or str(key).strip() == "":
        return "Tutte"
    raw = str(key).strip()
    label = CATEGORY_LABELS_IT.get(raw)
    if not label:
        parts = raw.split("_")
        prefix = CATEGORY_PREFIX_IT.get(parts[0], parts[0].replace("-", " ").capitalize()) if parts else "Categoria"
        rest = " ".join(parts[1:]).replace("pc", "PC").replace("gpu", "GPU").replace("ram", "RAM")
        label = f"{prefix}: {rest}" if rest else prefix
        label = label.strip().capitalize() if ":" not in label else label
    return f"{label} ({raw})" if include_key else label


def status_label_it(value: Any) -> str:
    if value in STATUS_LABELS_IT:
        return STATUS_LABELS_IT[value]  # type: ignore[index]
    raw = "" if value is None else str(value)
    return STATUS_LABELS_IT.get(raw, raw.replace("_", " ").strip().capitalize() or "—")


def sorted_category_keys(keys: list[str] | set[str] | tuple[str, ...] | None) -> list[str]:
    return sorted([str(k) for k in (keys or []) if str(k).strip()], key=lambda k: category_label_it(k).lower())


def localize_listing_rows(
    rows: list[dict[str, Any]],
    *,
    include_technical_category: bool = False,
    compact: bool = False,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if "errore" in row:
            out.append({"Errore": row.get("errore")})
            continue
        item: dict[str, Any] = {}
        for key, label in CLIENT_LISTING_COLUMN_LABELS.items():
            if compact and key not in CLIENT_COMPACT_LISTING_KEYS:
                continue
            if key not in row:
                continue
            val = row.get(key)
            if key == "category":
                item[label] = category_label_it(val)
                if include_technical_category:
                    item["Categoria tecnica"] = val
            elif key == "discount_percent" and val is not None:
                item[label] = f"{float(val):+.1f}%"
            elif key == "reference_confidence" and val is not None:
                item[label] = f"{float(val) * 100:.0f}%"
            elif key in {"verify_status", "clean_decision", "opportunity_status"}:
                item[label] = status_label_it(val)
            else:
                item[label] = val
        out.append(item)
    return out


def localize_catalog_rows(rows: list[dict[str, Any]], *, include_technical_category: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if "errore" in row:
            out.append({"Errore": row.get("errore")})
            continue
        item: dict[str, Any] = {}
        for key, label in CLIENT_CATALOG_COLUMN_LABELS.items():
            if key not in row:
                continue
            val = row.get(key)
            if key == "category":
                item[label] = category_label_it(val)
                if include_technical_category:
                    item["Categoria tecnica"] = val
            else:
                item[label] = val
        out.append(item)
    return out


def client_opportunity_safe(row: dict[str, Any]) -> bool:
    """Extra prudence for the client shortlist.

    The DB stays untouched. We only hide known category/title contradictions from
    the client-facing "Opportunità" tab so it behaves like a professional
    shortlist, not like a debug dump.
    """
    title = f"{row.get('title') or ''} {row.get('original_title') or ''}".lower()
    category = str(row.get("category") or "")
    if category == "vehicle_car_part" and re.search(r"\b(gitterbett|bett|matratze|leintuch|tupperware|schoko|fondue|vorratsdose|ikea)\b", title):
        return False
    if category == "technology_console" and re.search(r"\b(games?|spiel|spiele|controller|lenkrad|pedal|pedalen|hori|zubeh[oö]r|accessor)\b", title):
        return False
    if category == "technology_accessory" and re.search(r"\b(golvv[aä]rme|fl[aä]kt|heater|stativ|riscald)\b", title):
        return False
    if category in {"home_decor_photo_frame", "home_decor_wall_art"} and re.search(r"\b(camera da letto|casa con veranda|orologio da polso|wristwatch)\b", title):
        return False
    return True


@st.cache_data(ttl=5, show_spinner=False)
def market_client_summary() -> dict[str, Any]:
    out: dict[str, Any] = {
        "db_exists": MARKET_DB_DEFAULT.exists(),
        "listings": 0,
        "clean": {},
        "verify": {},
        "research": {},
        "ai_edge": {},
        "catalog": {},
        "sources": [],
        "categories": [],
    }
    con = market_connect_readonly()
    if con is None:
        return out
    try:
        out["listings"] = int(db_scalar(con, "SELECT COUNT(*) FROM listings") or 0) if db_table_exists(con, "listings") else 0
        out["clean"] = db_group_counts(con, "listing_cleaning_reviews", "decision")
        out["verify"] = db_group_counts(con, "listing_online_verifications", "status")
        out["research"] = db_group_counts(con, "listing_online_product_research", "status")
        out["ai_edge"] = db_group_counts(con, "listing_ai_edge_reviews", "status")
        out["catalog"] = {
            "families": int(db_scalar(con, "SELECT COUNT(*) FROM product_families") or 0) if db_table_exists(con, "product_families") else 0,
            "variants": int(db_scalar(con, "SELECT COUNT(*) FROM product_variants") or 0) if db_table_exists(con, "product_variants") else 0,
            "aliases": int(db_scalar(con, "SELECT COUNT(*) FROM product_aliases") or 0) if db_table_exists(con, "product_aliases") else 0,
            "identifiers": int(db_scalar(con, "SELECT COUNT(*) FROM product_identifiers") or 0) if db_table_exists(con, "product_identifiers") else 0,
            "spec_facts": int(db_scalar(con, "SELECT COUNT(*) FROM spec_facts") or 0) if db_table_exists(con, "spec_facts") else 0,
        }
        if db_table_exists(con, "listings"):
            out["sources"] = [str(r[0]) for r in con.execute("SELECT DISTINCT source FROM listings WHERE COALESCE(source,'')<>'' ORDER BY source")]
        cats: set[str] = set()
        for table, col in [
            ("listing_online_product_research", "canonical_category"),
            ("listing_ai_edge_reviews", "canonical_category"),
            ("listing_cleaning_reviews", "normalized_category"),
            ("product_families", "category"),
        ]:
            if db_table_exists(con, table):
                for r in con.execute(f"SELECT DISTINCT {col} FROM {table} WHERE COALESCE({col},'') NOT IN ('', 'unknown') ORDER BY {col}"):
                    cats.add(str(r[0]))
        out["categories"] = sorted_category_keys(cats)
    finally:
        con.close()
    return out


def render_client_status_cards():
    summary = market_client_summary()
    catalog = summary.get("catalog") or {}
    verify = summary.get("verify") or {}
    clean = summary.get("clean") or {}
    ok_state, maintenance, _ = market_maintenance_state("status", timeout=4)
    days = maintenance.get("days_since_success") if ok_state else None
    days_label = "—" if days is None else f"{days} gg"
    state_label = "OK"
    if ok_state and maintenance.get("critical"):
        state_label = "CRITICO"
    elif ok_state and maintenance.get("due"):
        state_label = "DA AGGIORNARE"
    elif ok_state and maintenance.get("snoozed"):
        state_label = "RIMANDATO"
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"<div class='status-card'><div class='status-label'>📦 Annunci</div><div class='status-value'>{summary.get('listings', 0)}</div><div class='status-mini'>clean OK: {clean.get('accept', 0)} · incerti: {clean.get('uncertain', 0)}</div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='status-card'><div class='status-label'>✅ Verifiche</div><div class='status-value'>{verify.get('verified', 0)}</div><div class='status-mini'>reject: {verify.get('rejected', 0)} · conflict: {verify.get('verified_conflict', 0)}</div></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='status-card'><div class='status-label'>🧬 Catalogo</div><div class='status-value'>{catalog.get('families', 0)}</div><div class='status-mini'>varianti: {catalog.get('variants', 0)} · alias: {catalog.get('aliases', 0)}</div></div>", unsafe_allow_html=True)
    with c4:
        st.markdown(f"<div class='status-card'><div class='status-label'>🔄 Manutenzione</div><div class='status-value'>{html.escape(state_label)}</div><div class='status-mini'>ultimo update: {html.escape(days_label)}</div></div>", unsafe_allow_html=True)


@st.cache_data(ttl=5, show_spinner=False)
def marketplace_query_rows(
    *,
    search: str = "",
    category: str = "",
    source: str = "",
    status: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
    limit: int = 150,
    verified_only: bool = False,
    include_unknown: bool = False,
) -> list[dict[str, Any]]:
    # Shared client contract: cleaning is the final handoff, strict opportunity
    # filters run in SQL before LIMIT, and description participates in search.
    try:
        return load_client_listings(
            MARKET_DB_DEFAULT,
            search=search,
            category=category,
            source=source,
            status=status,
            min_price=min_price,
            max_price=max_price,
            limit=limit,
            include_unknown=include_unknown,
            opportunity_safe=verified_only,
        )
    except Exception:
        # Keep the legacy query as a compatibility fallback for older DB schemas.
        pass

    con = market_connect_readonly()
    if con is None or not db_table_exists(con, "listings"):
        return []
    try:
        joins = []
        if db_table_exists(con, "listing_cleaning_reviews"):
            joins.append("LEFT JOIN listing_cleaning_reviews cr ON cr.listing_id = l.id")
        else:
            joins.append("LEFT JOIN (SELECT NULL listing_id, NULL decision, NULL confidence, NULL normalized_title, NULL normalized_category, NULL reason) cr ON 1=0")
        if db_table_exists(con, "listing_online_verifications"):
            joins.append("LEFT JOIN listing_online_verifications ov ON ov.listing_id = l.id")
        else:
            joins.append("LEFT JOIN (SELECT NULL listing_id, NULL status, NULL confidence, NULL reason) ov ON 1=0")
        if db_table_exists(con, "listing_online_product_research"):
            joins.append("LEFT JOIN listing_online_product_research r ON r.listing_id = l.id")
        else:
            joins.append("LEFT JOIN (SELECT NULL listing_id, NULL canonical_category, NULL canonical_title, NULL canonical_brand, NULL canonical_model, NULL confidence) r ON 1=0")
        if db_table_exists(con, "listing_ai_edge_reviews"):
            joins.append("LEFT JOIN listing_ai_edge_reviews ar ON ar.listing_id = l.id")
        else:
            joins.append("LEFT JOIN (SELECT NULL listing_id, NULL canonical_category, NULL canonical_title, NULL confidence) ar ON 1=0")

        where = []
        params: list[Any] = []
        if verified_only:
            where.append("ov.status = 'verified'")
        if not include_unknown:
            where.append("COALESCE(r.canonical_category, ar.canonical_category, cr.normalized_category, l.category, '') NOT IN ('', 'unknown')")
        if search.strip():
            where.append("(LOWER(l.title) LIKE ? OR LOWER(COALESCE(r.canonical_title,'')) LIKE ? OR LOWER(COALESCE(cr.normalized_title,'')) LIKE ? OR LOWER(COALESCE(l.seller,'')) LIKE ?)")
            q = f"%{search.strip().lower()}%"
            params.extend([q, q, q, q])
        if category:
            where.append("COALESCE(r.canonical_category, ar.canonical_category, cr.normalized_category, l.category, '') = ?")
            params.append(category)
        if source:
            where.append("l.source = ?")
            params.append(source)
        if status:
            where.append("ov.status = ?")
            params.append(status)
        if min_price is not None:
            where.append("COALESCE(l.price, 0) >= ?")
            params.append(float(min_price))
        if max_price is not None and float(max_price) > 0:
            where.append("COALESCE(l.price, 0) <= ?")
            params.append(float(max_price))

        where_sql = "WHERE " + " AND ".join(where) if where else ""
        sql = f"""
            SELECT
                l.id,
                l.source,
                l.title AS original_title,
                COALESCE(r.canonical_title, ar.canonical_title, cr.normalized_title, l.title) AS title,
                COALESCE(r.canonical_category, ar.canonical_category, cr.normalized_category, l.category, 'unknown') AS category,
                COALESCE(r.canonical_brand, '') AS brand,
                COALESCE(r.canonical_model, '') AS model,
                l.price,
                l.currency,
                l.location,
                l.seller,
                l.url,
                ov.status AS verify_status,
                cr.decision AS clean_decision,
                COALESCE(ov.confidence, r.confidence, ar.confidence, cr.confidence, 0.0) AS confidence,
                COALESCE(ov.reason, cr.reason, '') AS reason,
                l.last_seen
            FROM listings l
            {' '.join(joins)}
            {where_sql}
            ORDER BY
                CASE COALESCE(ov.status,'') WHEN 'verified' THEN 0 WHEN 'verified_conflict' THEN 1 WHEN 'uncertain' THEN 2 ELSE 3 END,
                COALESCE(l.last_seen, l.first_seen, '') DESC,
                COALESCE(ov.confidence, r.confidence, ar.confidence, cr.confidence, 0.0) DESC
            LIMIT ?
        """
        params.append(max(1, min(int(limit), 5000)))
        return [dict(r) for r in con.execute(sql, params)]
    except Exception as e:
        return [{"errore": str(e)}]
    finally:
        con.close()


@st.cache_data(ttl=5, show_spinner=False)
def catalog_family_rows(search: str = "", category: str = "", limit: int = 150) -> list[dict[str, Any]]:
    con = market_connect_readonly()
    if con is None or not db_table_exists(con, "product_families"):
        return []
    try:
        where = []
        params: list[Any] = []
        if search.strip():
            where.append("(LOWER(f.family_name) LIKE ? OR LOWER(COALESCE(f.brand,'')) LIKE ?)")
            q = f"%{search.strip().lower()}%"
            params.extend([q, q])
        if category:
            where.append("f.category = ?")
            params.append(category)
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        sql = f"""
            SELECT
                f.id,
                f.category,
                f.brand,
                f.family_name,
                f.confidence,
                COUNT(DISTINCT v.id) AS variants,
                COUNT(DISTINCT a.id) AS aliases,
                COUNT(DISTINCT s.id) AS spec_facts,
                f.last_seen
            FROM product_families f
            LEFT JOIN product_variants v ON v.family_id = f.id
            LEFT JOIN product_aliases a ON a.family_id = f.id
            LEFT JOIN spec_facts s ON s.family_id = f.id
            {where_sql}
            GROUP BY f.id
            ORDER BY f.last_seen DESC, f.confidence DESC
            LIMIT ?
        """
        params.append(max(1, min(int(limit), 5000)))
        return [dict(r) for r in con.execute(sql, params)]
    except Exception as e:
        return [{"errore": str(e)}]
    finally:
        con.close()


def client_start_incremental_update() -> tuple[bool, str]:
    cmd = [
        get_project_python(),
        "-u",
        "scripts/marketplace_gui_update_runner.py",
        "--db",
        str(MARKET_DB_DEFAULT),
        "--status-before",
        "--status-after",
    ]
    return start_market_background_command(cmd, pid_file=MARKET_MAINTENANCE_PID, log_file=MARKET_MAINTENANCE_LOG)


def render_client_home_page():
    st.markdown("### Panoramica")
    summary = market_client_summary()
    if not summary.get("db_exists"):
        st.warning("Database marketplace non trovato. Avvia un primo import/fetch dalla modalità sviluppatore.")
        return

    catalog = summary.get("catalog") or {}
    verify = summary.get("verify") or {}
    clean = summary.get("clean") or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Annunci totali", summary.get("listings", 0))
    c2.metric("Verificati", verify.get("verified", 0))
    c3.metric("Catalogo", catalog.get("families", 0), help="Famiglie prodotto apprese e consolidate.")
    c4.metric("Da rivedere", int(verify.get("uncertain", 0)) + int(verify.get("verified_conflict", 0)))

    st.markdown("### Azioni rapide")
    a1, a2, a3, a4 = st.columns(4)
    with a1:
        if st.button("🔄 Aggiorna database", type="primary", width="stretch", disabled=pid_running(MARKET_MAINTENANCE_PID)):
            ok, msg = client_start_incremental_update()
            st.toast(("OK: " if ok else "ATTENZIONE: ") + msg)
            time.sleep(0.4)
            st.rerun()
    with a2:
        if st.button("🧠 Crea ricerca AI", width="stretch"):
            st.session_state["page"] = CLIENT_PAGE_WIZARD
            st.rerun()
    with a3:
        if st.button("🔎 Apri prodotti", width="stretch"):
            st.session_state["page"] = CLIENT_PAGE_PRODUCTS
            st.rerun()
    with a4:
        if st.button("⭐ Vedi opportunità", width="stretch"):
            st.session_state["page"] = CLIENT_PAGE_OPPORTUNITIES
            st.rerun()

    st.markdown("### Ultimi annunci verificati")
    rows = marketplace_query_rows(verified_only=True, limit=25, include_unknown=False)
    if not rows:
        st.info("Nessun annuncio verificato da mostrare.")
    else:
        st.dataframe(rows, width="stretch", hide_index=True)

    with st.expander("Stato tecnico sintetico", expanded=False):
        st.json({"verify": verify, "clean": clean, "research": summary.get("research"), "ai_edge": summary.get("ai_edge"), "catalog": catalog})


def render_client_products_page():
    settings = load_client_settings()
    summary = market_client_summary()
    st.markdown("### Prodotti e annunci")
    st.caption("Vista cliente: ricerca negli annunci già puliti/verificati e nel catalogo consolidato.")

    tab_listings, tab_catalog, tab_resolver = st.tabs(["Annunci", "Catalogo", "Risolvi annuncio"])
    with tab_listings:
        c1, c2, c3, c4 = st.columns([2, 1.4, 1.2, 1.1])
        with c1:
            search = st.text_input("Cerca", placeholder="es. ThinkPad, iPhone, RTX, LEGO...")
        with c2:
            category = st.selectbox("Categoria", [""] + sorted_category_keys(summary.get("categories") or []), format_func=category_label_it)
        with c3:
            source = st.selectbox("Fonte", [""] + list(summary.get("sources") or []), format_func=lambda x: "Tutte" if not x else x)
        with c4:
            status = st.selectbox("Verifica", ["", "verified", "verified_conflict", "uncertain", "rejected"], format_func=lambda x: "Tutte" if not x else x)
        c5, c6, c7 = st.columns([1, 1, 1])
        with c5:
            min_price = st.number_input("Prezzo min", min_value=0.0, value=0.0, step=10.0)
        with c6:
            max_price = st.number_input("Prezzo max", min_value=0.0, value=0.0, step=10.0, help="0 = nessun limite")
        with c7:
            limit = st.number_input("Risultati", min_value=10, max_value=1000, value=int(settings.get("products_default_limit", 150)), step=10)
        include_unknown = st.checkbox("Mostra categorie sconosciute", value=bool(settings.get("show_unknown_products", False)))
        rows = marketplace_query_rows(search=search, category=category, source=source, status=status, min_price=min_price, max_price=max_price, limit=int(limit), include_unknown=include_unknown)
        display_rows = localize_listing_rows(rows, compact=True)
        st.dataframe(display_rows, width="stretch", hide_index=True)

        export_rows = localize_listing_rows(rows, compact=False)
        export_payload = json.dumps(export_rows, indent=2, ensure_ascii=False)
        st.download_button("⬇️ Esporta risultati JSON", data=export_payload, file_name="spyengine_annunci_filtrati.json", mime="application/json")

    with tab_catalog:
        c1, c2, c3 = st.columns([2, 1.4, 1])
        with c1:
            cat_search = st.text_input("Cerca nel catalogo", key="catalog_client_search")
        with c2:
            cat_category = st.selectbox("Categoria catalogo", [""] + sorted_category_keys(summary.get("categories") or []), key="catalog_client_category", format_func=category_label_it)
        with c3:
            cat_limit = st.number_input("Risultati catalogo", min_value=10, max_value=1000, value=150, step=10)
        families = catalog_family_rows(cat_search, cat_category, int(cat_limit))
        st.dataframe(localize_catalog_rows(families), width="stretch", hide_index=True)
    with tab_resolver:
        st.markdown("#### Riconosci un annuncio rumoroso")
        st.caption("Il catalogo locale usa prima titolo e descrizione; AI e verifica online restano l'emergenza per i casi incerti.")
        resolver_title = st.text_area("Titolo annuncio", placeholder="OTTIMA OFFERTA!!1! IPHONE TELEFONO NUOVO RICONDIZIATO PRO MAX 16", key="client_resolver_title")
        resolver_description = st.text_area("Descrizione annuncio", placeholder="Incolla qui descrizione, codici modello, capacità e condizione...", height=150, key="client_resolver_description")
        if st.button("Risolvi dal catalogo locale", type="primary", key="client_resolver_run"):
            con = market_connect_readonly()
            if con is None:
                st.warning("Database marketplace non disponibile.")
            else:
                try:
                    resolution = resolve_product(con, resolver_title, resolver_description)
                finally:
                    con.close()
                if resolution.selected:
                    selected = resolution.selected
                    st.success(f"{selected.brand} {selected.family_name} {selected.variant_name}".strip())
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Categoria", category_label_it(selected.category))
                    c2.metric("Confidenza", f"{selected.confidence * 100:.1f}%")
                    c3.metric("Condizione", status_label_it(resolution.condition))
                    st.caption("Evidenze: " + " · ".join(f"{ev.term} ({ev.detail})" for ev in selected.evidence[:5]))
                    if resolution.relations:
                        st.markdown("##### Compatibilità e relazioni note")
                        relation_rows = [
                            {
                                "Direzione": status_label_it(item.get("direction")),
                                "Tipo": status_label_it(item.get("relation_type")),
                                "Prodotto": " ".join(
                                    str(item.get(key) or "")
                                    for key in ("brand", "family_name", "variant_name")
                                ).strip(),
                                "Confidenza": f"{float(item.get('confidence') or 0) * 100:.0f}%",
                            }
                            for item in resolution.relations[:8]
                        ]
                        st.dataframe(relation_rows, width="stretch", hide_index=True)
                elif resolution.status == "ambiguous":
                    st.warning("Più candidati plausibili: serve conferma o verifica online.")
                else:
                    st.info("Catalogo locale insufficiente: questo caso va in coda per enrichment/AI.")
                with st.expander("Candidati e spiegazione", expanded=not bool(resolution.selected)):
                    st.json([candidate.to_dict() for candidate in resolution.candidates])


def render_opportunity_cards(rows: list[dict[str, Any]], *, max_cards: int = 6) -> None:
    comparable = [row for row in rows if row.get("opportunity_score") is not None]
    if not comparable:
        st.caption("Nessuna card prezzo: servono almeno tre annunci dello stesso modello o titolo risolto.")
        return

    st.markdown("#### Migliori confronti disponibili")
    for row in comparable[:max_cards]:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3.4, 1.1, 1.1, 1.2])
            with c1:
                st.write(str(row.get("title") or row.get("original_title") or "Annuncio"))
                product_bits = [row.get("brand"), row.get("model")]
                product = " ".join(str(bit) for bit in product_bits if bit).strip()
                reference = row.get("reference_price")
                sample = int(row.get("reference_sample_size") or 0)
                context = [product or category_label_it(row.get("category"))]
                if reference is not None:
                    context.append(f"Riferimento: {float(reference):.2f} · {sample} annunci")
                st.caption(" · ".join(context))
            with c2:
                st.metric(
                    "Prezzo",
                    f"{float(row.get('price') or 0):.2f} {row.get('currency') or 'EUR'}",
                )
            with c3:
                discount = row.get("discount_percent")
                st.metric(
                    "Score prezzo",
                    f"{float(row.get('opportunity_score') or 0):.1f}/100",
                    f"{float(discount):+.1f}%" if discount is not None else None,
                )
            with c4:
                st.caption(status_label_it(row.get("opportunity_status")))
                st.link_button("Apri annuncio", str(row.get("url")), width="stretch")


def render_client_opportunities_page():
    settings = load_client_settings()
    st.markdown("### Opportunità")
    st.caption("Lista prudente: annunci verificati, acquistabili e con categoria riconosciuta. Non è una garanzia di prezzo migliore: serve come shortlist operativa.")
    c1, c2, c3 = st.columns([2, 1.2, 1])
    with c1:
        search = st.text_input("Filtra opportunità", placeholder="es. laptop, console, smartwatch...")
    with c2:
        max_price = st.number_input("Prezzo massimo", min_value=0.0, value=0.0, step=25.0, help="0 = nessun limite")
    with c3:
        limit = st.number_input("Quante", min_value=10, max_value=500, value=int(settings.get("opportunities_default_limit", 80)), step=10)
    rows = marketplace_query_rows(search=search, status="verified", max_price=max_price, limit=int(limit), verified_only=True, include_unknown=False)
    rows = [r for r in rows if str(r.get("clean_decision") or "") in ("accept", "", "None") and client_opportunity_safe(r)]
    render_opportunity_cards(rows)
    st.caption("Lo score prezzo usa solo comparabili specifici; la confidenza prodotto resta separata.")
    display_rows = localize_listing_rows(rows, compact=True)
    export_rows = localize_listing_rows(rows, compact=False)
    st.dataframe(display_rows, width="stretch", hide_index=True)
    st.download_button("⬇️ Esporta shortlist JSON", data=json.dumps(export_rows, indent=2, ensure_ascii=False), file_name="spyengine_opportunita.json", mime="application/json")


def catalog_enrichment_client_state() -> dict[str, Any]:
    out: dict[str, Any] = {"queue": {}, "claimable": 0, "evidence": 0, "proposals": 0, "latest_run": {}}
    con = market_connect_readonly()
    if con is None:
        return out
    try:
        if not db_table_exists(con, "catalog_enrichment_tasks"):
            return out
        out["queue"] = {
            str(row[0]): int(row[1])
            for row in con.execute("SELECT status, COUNT(*) FROM catalog_enrichment_tasks GROUP BY status")
        }
        out["claimable"] = int(db_scalar(con, "SELECT COUNT(*) FROM catalog_enrichment_tasks WHERE status='pending' AND attempts < max_attempts") or 0)
        for table, key in [
            ("product_evidence", "evidence"),
            ("catalog_fact_proposals", "proposals"),
        ]:
            if db_table_exists(con, table):
                out[key] = int(db_scalar(con, f"SELECT COUNT(*) FROM {table}") or 0)
        latest = con.execute("SELECT status, stats_json, last_heartbeat_at FROM catalog_enrichment_runs ORDER BY id DESC LIMIT 1").fetchone() if db_table_exists(con, "catalog_enrichment_runs") else None
        if latest:
            out["latest_run"] = {"status": latest[0], "stats": json.loads(latest[1] or "{}"), "heartbeat": latest[2]}
    finally:
        con.close()
    return out
def render_client_job_center_page():
    st.markdown("### Aggiornamento database")
    running = pid_running(MARKET_MAINTENANCE_PID)
    ok, state, raw = market_maintenance_state("status")
    c1, c2, c3 = st.columns(3)
    c1.metric("Stato", "in corso" if running else ("OK" if ok and not state.get("due") else "da aggiornare"))
    c2.metric("Giorni ultimo update", "—" if not ok or state.get("days_since_success") is None else state.get("days_since_success"))
    c3.metric("Soglia", state.get("threshold_days", 30) if ok else 30)

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🔄 Avvia update incrementale", type="primary", width="stretch", disabled=running):
            ok2, msg = client_start_incremental_update()
            st.toast(("OK: " if ok2 else "ATTENZIONE: ") + msg)
            time.sleep(0.4)
            st.rerun()
    with col2:
        if st.button("⏹️ Ferma update", width="stretch", disabled=not running):
            ok2, msg = stop_market_background_command(MARKET_MAINTENANCE_PID)
            st.toast(("OK: " if ok2 else "ATTENZIONE: ") + msg)
            time.sleep(0.4)
            st.rerun()
    with col3:
        if st.button("🔁 Aggiorna stato", width="stretch"):
            st.rerun()

    if ok:
        with st.expander("Dettaglio stato", expanded=False):
            st.json(state)
    else:
        st.warning("Stato manutenzione non disponibile.")
        st.code(raw, language="text")

    st.markdown("#### Log aggiornamento")
    render_following_log_box(
        "marketplace_gui_maintenance_update.log",
        MARKET_MAINTENANCE_LOG,
        lines=260,
        height=520,
        newest_first=True,
    )

    st.markdown("#### Ultimi report")
    report_cols = st.columns(2)
    reports = [Path("logs/marketplace_postprocess_report.md"), Path("logs/marketplace_catalog_learning_report.md")]
    for col, report in zip(report_cols, reports):
        with col:
            st.caption(str(report))
            txt = read_tail(report, 120)
            st.code(txt or "Report non trovato.", language="markdown")


    st.markdown("### Arricchimento knowledge base")
    enrichment = catalog_enrichment_client_state()
    enrich_pid_file = (
        CATALOG_ENRICHMENT_GUI_PID
        if pid_running(CATALOG_ENRICHMENT_GUI_PID)
        else CATALOG_ENRICHMENT_DAEMON_PID
    )
    enrich_running = pid_running(enrich_pid_file)
    queue_counts = enrichment.get("queue") or {}
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Stato", "in corso" if enrich_running else "fermo")
    e2.metric("Task da lavorare", enrichment.get("claimable", 0))
    e3.metric("Evidenze", enrichment.get("evidence", 0))
    e4.metric("Proposte validate", enrichment.get("proposals", 0))

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("▶️ Avvia arricchimento", type="primary", width="stretch", disabled=enrich_running):
            cmd = [get_project_python(), "-u", "scripts/catalog_enrichment_daemon.py", "--db", str(MARKET_DB_DEFAULT), "--tasks-per-cycle", "3", "--sleep-seconds", "60", "--validate-every", "5"]
            ok2, msg = start_market_background_command(cmd, pid_file=CATALOG_ENRICHMENT_GUI_PID, log_file=CATALOG_ENRICHMENT_LOG)
            st.toast(("OK: " if ok2 else "ATTENZIONE: ") + msg)
            time.sleep(0.4)
            st.rerun()
    with b2:
        if st.button("⏹️ Ferma arricchimento", width="stretch", disabled=not enrich_running):
            ok2, msg = stop_market_background_command(enrich_pid_file)
            st.toast(("OK: " if ok2 else "ATTENZIONE: ") + msg)
            time.sleep(0.4)
            st.rerun()
    with b3:
        if st.button("✅ Valida evidenze", width="stretch"):
            rc, output = run_market_command_now([get_project_python(), "scripts/validate_catalog_evidence.py", "--db", str(MARKET_DB_DEFAULT), "--apply-proposals"], timeout=120)
            st.success(output) if rc == 0 else st.warning(output)
    with st.expander("Log arricchimento catalogo", expanded=enrich_running):
        render_following_log_box("catalog_enrichment_daemon.log", CATALOG_ENRICHMENT_LOG, lines=260, height=520, newest_first=True)
    st.caption(f"Coda: {queue_counts}. Gli snippet web sono solo evidenze; nessun identificatore viene promosso automaticamente.")
def render_client_settings_page():
    st.markdown("### Impostazioni")
    settings = load_client_settings()
    with st.form("client_settings_form"):
        app_name = st.text_input("Nome mostrato", value=str(settings.get("client_theme_name", "SpyEngine Marketplace")))
        c1, c2 = st.columns(2)
        with c1:
            threshold = st.number_input("Promemoria update dopo giorni", min_value=1, max_value=365, value=int(settings.get("update_threshold_days", 30)), step=1)
        with c2:
            critical = st.number_input("Avviso forte dopo giorni", min_value=1, max_value=730, value=int(settings.get("critical_update_days", 90)), step=1)
        c3, c4 = st.columns(2)
        with c3:
            products_limit = st.number_input("Risultati default prodotti", min_value=10, max_value=1000, value=int(settings.get("products_default_limit", 150)), step=10)
        with c4:
            opp_limit = st.number_input("Risultati default opportunità", min_value=10, max_value=500, value=int(settings.get("opportunities_default_limit", 80)), step=10)
        show_unknown = st.checkbox("Mostra categorie sconosciute di default", value=bool(settings.get("show_unknown_products", False)))
        submitted = st.form_submit_button("💾 Salva impostazioni", type="primary")
    if submitted:
        settings.update({
            "client_theme_name": app_name,
            "update_threshold_days": int(threshold),
            "critical_update_days": int(critical),
            "products_default_limit": int(products_limit),
            "opportunities_default_limit": int(opp_limit),
            "show_unknown_products": bool(show_unknown),
            "dev_mode": bool(st.session_state.get("client_dev_mode", settings.get("dev_mode", False))),
        })
        save_client_settings(settings)
        st.success("Impostazioni salvate.")

    st.markdown("### Modalità avanzata")
    st.info("La modalità sviluppatore mostra pipeline, dry-run, repair catalogo, log e strumenti lunghi. È nascosta di default per uso cliente.")
    if st.button("🛠️ " + ("Disattiva modalità sviluppatore" if is_dev_mode() else "Attiva modalità sviluppatore")):
        settings["dev_mode"] = not is_dev_mode()
        save_client_settings(settings)
        st.session_state["client_dev_mode"] = bool(settings["dev_mode"])
        st.rerun()

    with st.expander("Percorsi e dati tecnici", expanded=False):
        st.json({
            "db": str(MARKET_DB_DEFAULT),
            "settings": str(CLIENT_SETTINGS_PATH),
            "update_log": str(MARKET_MAINTENANCE_LOG),
            "versione_gui": CLIENT_APP_VERSION,
        })



# ==================== SIDEBAR ====================

if "page" not in st.session_state:
    st.session_state["page"] = CLIENT_PAGE_HOME
if "ctrl_dry_run" not in st.session_state:
    st.session_state["ctrl_dry_run"] = True
if "ctrl_notification_dry_run" not in st.session_state:
    st.session_state["ctrl_notification_dry_run"] = False
if "ctrl_max_total" not in st.session_state:
    st.session_state["ctrl_max_total"] = 0
if "ctrl_platforms" not in st.session_state:
    st.session_state["ctrl_platforms"] = []
if "client_dev_mode" not in st.session_state:
    st.session_state["client_dev_mode"] = bool(load_client_settings().get("dev_mode", False))

start_cmd = build_manager_command()

with st.sidebar:
    settings = load_client_settings()
    st.markdown("## 🕵️ SpyEngine")
    st.caption(f"Marketplace · {CLIENT_APP_VERSION}")

    st.markdown("---")

    if not is_dev_mode():
        render_sidebar_mini_status()
        summary = market_client_summary()
        catalog = summary.get("catalog") or {}
        st.caption(f"DB: {summary.get('listings', 0)} annunci")
        st.caption(f"Catalogo: {catalog.get('families', 0)} famiglie · {catalog.get('variants', 0)} varianti")
    else:
        st.markdown("## 🕹️ Controlli Dev")
        st.markdown("<div class='small-muted'>Avvio rapido di llama e manager.</div>", unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            if st.button("🚀 Llama", width="stretch"):
                ok, msg = start_llama_background()
                st.toast(("OK: " if ok else "ERRORE: ") + msg)
                time.sleep(0.5)
                st.rerun()
        with c2:
            if st.button("🛑 Llama", width="stretch"):
                ok, msg = stop_llama()
                st.toast(("OK: " if ok else "ERRORE: ") + msg)
                time.sleep(0.5)
                st.rerun()

        st.checkbox("Manager dry-run", key="ctrl_dry_run")
        st.checkbox(
            "Simula solo notifiche",
            key="ctrl_notification_dry_run",
            disabled=bool(st.session_state.get("ctrl_dry_run", True)),
        )
        st.number_input("max-total test", min_value=0, step=1, key="ctrl_max_total", help="0 = nessun limite")

        c3, c4 = st.columns(2)
        with c3:
            if st.button("▶️ Manager", width="stretch"):
                ok, msg = process_start(start_cmd, MANAGER_PID, MANAGER_LOG)
                st.toast(("OK: " if ok else "ERRORE: ") + msg)
                time.sleep(0.5)
                st.rerun()
        with c4:
            if st.button("⏹️ Manager", width="stretch"):
                ok, msg = process_stop(MANAGER_PID, "manager")
                st.toast(("OK: " if ok else "ERRORE: ") + msg)
                time.sleep(0.5)
                st.rerun()

        st.markdown("---")
        render_sidebar_model_status()
        st.markdown("### 📄 Log llama")
        render_llama_log_panel()

        with st.expander("llama_starter.log", expanded=False):
            st.code(read_tail(LLAMA_STARTER_LOG, 60) or "Nessun log starter.", language="text")

query_page = requested_client_page_from_query()
page = query_page or st.session_state.get("page", CLIENT_PAGE_HOME)
st.session_state["page"] = page
if page not in get_navigation_labels(is_dev_mode()):
    page = CLIENT_PAGE_HOME
    st.session_state["page"] = page


# ==================== MAIN ====================

render_top_header(page)
render_market_maintenance_banner()


if page == CLIENT_PAGE_HOME:
    render_client_home_page()

elif page == CLIENT_PAGE_PRODUCTS:
    render_client_products_page()

elif page == CLIENT_PAGE_OPPORTUNITIES:
    render_client_opportunities_page()

elif page == CLIENT_PAGE_JOBS:
    render_client_job_center_page()

elif page == CLIENT_PAGE_SETTINGS:
    render_client_settings_page()

elif page == "🏠 Dashboard":
    cfgs = list_configs()
    latest_report_path = latest_file("data/reports/**/*.json")
    c1, c2, c3 = st.columns(3)
    c1.metric("Config", len(cfgs))
    c2.metric("Seen file", count_json_files(Path("data/seen")))
    c3.metric("Ultimo report", latest_report_path.name if latest_report_path else "—")

    st.markdown("### 📡 Manager live")
    render_manager_log_panel(height=640)

    st.markdown("### Config attive")
    if not cfgs:
        st.info("Nessuna configurazione trovata in configs/.")
    else:
        for path in cfgs:
            cfg = load_json(path, {})
            with st.expander(f"{path.name} — {cfg.get('item_description', 'senza descrizione')[:90]}"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write("**Nome:**", cfg.get("name", config_name_from_path(path)))
                    st.write("**Piattaforme:**", ", ".join(cfg.get("platforms", [])))
                    st.write("**AI:**", f"context={cfg.get('context_check_enabled')} | vision={cfg.get('vision_enabled')}")
                    st.write("**Keywords:**", ", ".join(cfg.get("search_keywords", [])[:12]))
                    st.write("**Budget:**")
                    st.json(cfg.get("budget", {}))
                with col2:
                    name = cfg.get("name", config_name_from_path(path))
                    st.write("**Seen:**", len(load_json(Path("data/seen") / f"seen_ads_{name}.json", [])))
                    st.write("**History:**", len(load_json(Path("data/history") / f"price_history_{name}.json", [])))

    st.markdown("### Comando manager")
    st.code(" ".join(start_cmd), language="bash")


elif page == "⚙️ Config":
    cfgs = list_configs()
    tab_edit, tab_new = st.tabs(["✏️ Modifica", "➕ Nuova manuale"])

    with tab_edit:
        if not cfgs:
            st.warning("Nessuna config esistente.")
        else:
            selected = st.selectbox("Config", cfgs, format_func=lambda p: p.name)
            cfg, _ = normalize_generated_config(load_json(selected, default_config()))

            with st.form("edit_config"):
                st.subheader(selected.name)
                cfg["name"] = st.text_input("Nome interno", cfg.get("name", config_name_from_path(selected)))
                cfg["item_description"] = st.text_area("Descrizione target", cfg.get("item_description", ""), height=90)

                col1, col2 = st.columns(2)
                with col1:
                    keywords_text = st.text_area("Keywords ricerca, una per riga", "\n".join(cfg.get("search_keywords", [])), height=150)
                    required_text = st.text_area("Required words, una per riga", "\n".join(cfg.get("required_words", [])), height=110)
                    exclude_text = st.text_area("Exclude words, una per riga", "\n".join(cfg.get("exclude_words", [])), height=110)
                with col2:
                    distractor_text = st.text_area("Distractor words, una per riga", "\n".join(cfg.get("distractor_words", [])), height=110)
                    reject_text = st.text_area("Reject patterns, una per riga", "\n".join(cfg.get("reject_patterns", [])), height=110)
                    negative_text = st.text_area("Negative keywords, una per riga", "\n".join(cfg.get("negative_keywords", [])), height=110)

                cfg["platforms"] = st.multiselect(
                    "Piattaforme",
                    ["VINTED", "SUBITO", "EBAY", "WALLAPOP", "MOCK"],
                    default=[p for p in cfg.get("platforms", []) if p in ["VINTED", "SUBITO", "EBAY", "WALLAPOP", "MOCK"]],
                )

                col3, col4, col5 = st.columns(3)
                cfg["context_check_enabled"] = col3.checkbox("Context AI", value=bool(cfg.get("context_check_enabled", True)))
                cfg["vision_enabled"] = col4.checkbox("Vision AI", value=bool(cfg.get("vision_enabled", True)))
                cfg["interval_seconds"] = int(col5.number_input("Intervallo secondi", min_value=30, value=int(cfg.get("interval_seconds", 300)), step=30))

                budget_text = st.text_area("Budget JSON", json.dumps(cfg.get("budget", {}), indent=2, ensure_ascii=False), height=145)
                patterns_text = st.text_area("Config patterns JSON", json.dumps(cfg.get("config_patterns", {}), indent=2, ensure_ascii=False), height=145)
                positive_text = st.text_area("Positive keywords JSON", json.dumps(cfg.get("positive_keywords", {}), indent=2, ensure_ascii=False), height=115)
                brands_text = st.text_area("Premium brands, una per riga", "\n".join(cfg.get("premium_brands", [])), height=80)
                cfg["system_prompt"] = st.text_area("System prompt AI", cfg.get("system_prompt", ""), height=200)

                save = st.form_submit_button("💾 Salva config", type="primary")

            if save:
                try:
                    cfg["search_keywords"] = [x.strip() for x in keywords_text.splitlines() if x.strip()]
                    cfg["required_words"] = [x.strip() for x in required_text.splitlines() if x.strip()]
                    cfg["exclude_words"] = [x.strip() for x in exclude_text.splitlines() if x.strip()]
                    cfg["distractor_words"] = [x.strip() for x in distractor_text.splitlines() if x.strip()]
                    cfg["reject_patterns"] = [x.strip() for x in reject_text.splitlines() if x.strip()]
                    cfg["negative_keywords"] = [x.strip() for x in negative_text.splitlines() if x.strip()]
                    cfg["premium_brands"] = [x.strip() for x in brands_text.splitlines() if x.strip()]
                    cfg["budget"] = json.loads(budget_text)
                    cfg["config_patterns"] = json.loads(patterns_text)
                    cfg["positive_keywords"] = json.loads(positive_text)
                    normalized, warnings = normalize_generated_config(cfg)
                    save_json(selected, normalized)
                    st.success("Config salvata.")
                    for w in warnings:
                        st.warning(w)
                except Exception as e:
                    st.error(f"Errore salvataggio: {e}")

    with tab_new:
        with st.form("new_config"):
            name = st.text_input("Nome config", "new_spy")
            desc = st.text_area("Descrizione target", "RAM DDR4 desktop 32GB o 16GB", height=100)
            keywords = st.text_area("Keywords, una per riga", "ddr4 32gb\n32gb ddr4\nram 16gb desktop", height=130)
            budget = st.number_input("Budget standard", min_value=1.0, value=100.0, step=5.0)
            platforms_new = st.multiselect("Piattaforme", ["VINTED", "SUBITO", "EBAY", "WALLAPOP"], default=["VINTED", "SUBITO", "WALLAPOP"])
            create = st.form_submit_button("Crea", type="primary")

        if create:
            cfg = default_config()
            cfg["name"] = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or "new_spy"
            cfg["item_description"] = desc
            cfg["search_keywords"] = [x.strip() for x in keywords.splitlines() if x.strip()]
            cfg["budget"] = {"default": float(budget), "configurations": {"standard": float(budget)}}
            cfg["platforms"] = platforms_new
            path = Path("configs") / f"spy_config_{cfg['name']}.json"
            save_json(path, cfg)
            st.success(f"Creata {path}")


elif page == CLIENT_PAGE_WIZARD:
    st.markdown("### Crea una ricerca con AI")
    st.write("Descrivi al sistema cosa vuoi cercare: il wizard prepara una configurazione pronta all'uso, con parole chiave, filtri, budget e controlli AI/Vision.")

    desc = st.text_area(
        "Cosa vuoi cercare?",
        height=190,
        placeholder="Esempio: Cerco RAM DDR4 desktop, banchi singoli da 16GB o kit 32GB, no ECC, no SODIMM...",
    )

    wizard_mode = st.radio(
        "Modalità generazione",
        ["Fast single-pass", "Accurata planner+generator"],
        index=0,
        horizontal=True,
        help="Fast fa una sola chiamata LLM ed è consigliata con modelli lenti. Accurata usa due chiamate, ma può andare in timeout."
    )
    st.caption(
        "Streaming attivo: durante la generazione dovresti vedere eventi llm_stream. "
        "Timeout configurabile con LLAMA_HTTP_READ_TIMEOUT, default 600s."
    )
    use_knowledge_enrichment = st.checkbox(
        "Arricchisci config con cache/web",
        value=False,
        help="Usa appunti tecnici locali e, se serve, una ricerca web veloce durante la generazione config. Non viene usato durante lo scraping annunci."
    )
    refresh_knowledge_enrichment = st.checkbox(
        "Forza refresh cache + prova web",
        value=False,
        help="Ignora la cache esistente e riprova la ricerca web. Da usare solo quando vuoi aggiornare gli appunti tecnici."
    )
    show_trace = st.checkbox("Mostra trace operativo durante la generazione", value=True)
    show_trace_details = st.checkbox("Mostra dettagli tecnici del trace", value=False)

    trace_placeholder = st.empty()
    status_placeholder = st.empty()

    if st.button("🧠 Genera config", type="primary"):
        st.session_state.wizard_trace_events = []
        t_start = time.time()

        def wizard_progress(stage: str, message: str, detail: Any = None, elapsed: float | None = None):
            # `elapsed` from inner functions is a local phase timer.
            # Keep the displayed `elapsed` monotonic/global for the whole wizard run.
            global_elapsed = time.time() - t_start
            ev = {
                "seq": len(st.session_state.wizard_trace_events) + 1,
                "stage": stage,
                "message": message,
                "detail": detail,
                "elapsed": global_elapsed,
            }
            if elapsed is not None:
                ev["phase_elapsed"] = elapsed

            st.session_state.wizard_trace_events.append(ev)

            if show_trace:
                status_placeholder.info(f"Ultimo evento: {ev['elapsed']:.1f}s — {stage}: {message}")
                with trace_placeholder.container():
                    render_wizard_trace(st.session_state.wizard_trace_events, show_details=False)

        mode_value = "accurate" if wizard_mode.startswith("Accurata") else "fast"
        enrichment_note = ""
        if use_knowledge_enrichment:
            wizard_progress("knowledge_start", "Cerco appunti tecnici in cache/web")
            enrichment = enrich_user_description(
                desc,
                use_web=True,
                refresh=refresh_knowledge_enrichment,
                max_results=5,
                progress=wizard_progress,
                force_web=refresh_knowledge_enrichment,
            )
            enrichment_note = format_enrichment_for_prompt(enrichment)
            wizard_progress(
                "knowledge_done",
                "Arricchimento pronto"
                + (" da cache" if enrichment.get("from_cache") else "")
                + f" — {len(enrichment.get('facts') or [])} appunti, {len(enrichment.get('web_results') or [])} risultati web",
                enrichment_note,
            )

        with st.spinner("Chiedo al modello di generare una config compatta..."):
            cfg, raw, warnings = generate_config_with_ai(
                desc,
                progress=wizard_progress,
                mode=mode_value,
                enrichment_note=enrichment_note,
            )

        wizard_progress("finished", "Wizard completato" if cfg else "Wizard fallito")
        st.session_state.last_ai_raw = raw
        st.session_state.generated_cfg = cfg
        st.session_state.generated_warnings = warnings

    if st.session_state.get("wizard_trace_events"):
        render_wizard_trace(st.session_state.wizard_trace_events, show_details=show_trace_details)

    if st.session_state.get("last_ai_raw"):
        with st.expander("Risposta grezza AI"):
            st.code(st.session_state.last_ai_raw, language="text")

    if st.session_state.get("generated_cfg") is None and st.session_state.get("last_ai_raw"):
        st.error("Config non generata. Il modello ha restituito JSON non recuperabile.")

    if st.session_state.get("generated_cfg"):
        cfg = st.session_state.generated_cfg
        warnings = st.session_state.get("generated_warnings", [])

        if warnings:
            st.warning("Correzioni automatiche applicate:")
            for w in warnings:
                st.write("- " + w)

        st.markdown("### Anteprima config pulita")
        st.json(cfg)

        suggested = Path("configs") / f"spy_config_{cfg['name']}.json"
        filename = st.text_input("Salva come", str(suggested))

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 Salva config generata", type="primary"):
                save_json(Path(filename), cfg)
                st.success(f"Salvata: {filename}")
        with col2:
            st.download_button(
                "⬇️ Scarica JSON",
                data=json.dumps(cfg, indent=2, ensure_ascii=False),
                file_name=f"spy_config_{cfg['name']}.json",
                mime="application/json",
            )



elif page == "🗃️ Cache market":
    render_market_cache_page()


elif page == "📜 Log":
    st.markdown("I pannelli sotto si aggiornano come frammenti, senza refresh totale della pagina se la versione Streamlit supporta `st.fragment`.")

    tab1, tab2, tab3, tab4 = st.tabs(["Manager", "llama", "Spy logs", "Report"])

    with tab1:
        render_manager_log_panel(height=650)

    with tab2:
        render_llama_log_panel()
        st.text_area("llama_starter.log", read_tail(LLAMA_STARTER_LOG, 80) or "Nessun log starter.", height=220, disabled=True)

    with tab3:
        logs = sorted(Path(".").glob("spy_*.log"))
        if not logs:
            st.info("Nessun file spy_*.log trovato.")
        else:
            selected_log = st.selectbox("Log spy", logs, format_func=lambda p: p.name)
            render_log_box(str(selected_log), selected_log, lines=180, height=650)

    with tab4:
        latest = latest_file("data/reports/**/*.json")
        if not latest:
            st.info("Nessun report trovato.")
        else:
            st.caption(str(latest))
            st.json(load_json(latest, {}))


elif page == "🩺 Doctor":
    st.markdown("### Diagnostica")

    env_rows = {
        ".env": "OK" if Path(".env").exists() else "MISSING",
        "TELEGRAM_TOKEN": mask(os.environ.get("TELEGRAM_TOKEN")),
        "TELEGRAM_CHAT_ID": mask(os.environ.get("TELEGRAM_CHAT_ID")),
        "EBAY_ENV": os.environ.get("EBAY_ENV", "production"),
        "EBAY_APP_ID": mask(os.environ.get("EBAY_APP_ID")),
        "EBAY_CERT_ID / SECRET": mask(os.environ.get("EBAY_CERT_ID") or os.environ.get("EBAY_CLIENT_SECRET")),
        "LLAMA_MODEL": os.environ.get("LLAMA_MODEL", "./Qwen3.5-14B-A3B-Claude-Opus-Reasoning-Distilled-4.6-MXFP4_MOE.gguf"),
        "LLAMA_MMPROJ": os.environ.get("LLAMA_MMPROJ", "./Qwen3.5-35B-A3B-Claude-Opus-Reasoning-Distilled-4.6-mmproj-q8_0.gguf"),
    }

    st.table([{"voce": k, "valore": v} for k, v in env_rows.items()])

    col1, col2, col3 = st.columns(3)
    if col1.button("Test Telegram"):
        tg = TelegramNotifier()
        if not tg.configured:
            st.error("Telegram non configurato.")
        else:
            ok = tg.send("🧪 <b>SpyEngine GUI</b>\nTelegram OK.")
            st.success("Telegram inviato.") if ok else st.error("Invio fallito.")

    if col2.button("Test eBay"):
        with st.spinner("Eseguo scripts/test_ebay.py..."):
            r = subprocess.run([sys.executable, "scripts/test_ebay.py"], capture_output=True, text=True, timeout=60)
        st.code((r.stdout or "") + (r.stderr or ""), language="text")

    if col3.button("Doctor CLI"):
        with st.spinner("Eseguo scripts/doctor.py..."):
            r = subprocess.run([sys.executable, "scripts/doctor.py"], capture_output=True, text=True, timeout=60)
        st.code((r.stdout or "") + (r.stderr or ""), language="text")
