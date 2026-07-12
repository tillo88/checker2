from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import HarvestListing
from .category_schema import category_keys
from .canonicalize import canonical_category_from_title


_VALID_CATALOG_CATEGORY_KEYS = set(category_keys())
_CATEGORY_ALIASES = {
    "technology_phone": "technology_smartphone",
    "technology_storage_ssd": "technology_storage",
    "technology_storage_hdd": "technology_storage",
}
_ICON_NOISE_RE = re.compile(
    r"\s*,\s*(?:ikon|icon|kuvake|icona|ikona)\s+(?:av|af|of|di|de|för|for).*$",
    re.I,
)

_STRONG_TITLE_OVERRIDE_CATEGORIES = {
    "technology_audio_headphones", "sports_fitness_equipment", "fashion_bag",
    "technology_accessory", "baby_child_car_seat", "home_furniture_chair",
    "toys_dollhouse", "toys_lego", "sports_billiards", "sports_fishing_lure",
    "vehicle_motorcycle_accessory", "tools_cutting_tool", "tools_measuring_caliper",
    "music_drums", "home_storage_container", "home_decor_photo_frame", "home_decor_wall_art",
}
_HAZARDOUS_OR_UNSUPPORTED_TITLE_RE = re.compile(
    r"\b(czynnik\s+ch[lł]odniczy|r134a|r404a|r407c|r410a|refrigerant|gas\s+refrigerante)\b",
    re.I,
)
_UNSUPPORTED_DOCUMENT_TITLE_RE = re.compile(
    r"\b(reich[-\s]*dokument|reich[-\s]*document|tysk\s+reich|originalt\s+tysk|historien\s+i\s+h[aå]nden|"
    r"dokument\s+fra\s+\d{4}|document\s+from\s+\d{4}|historical\s+document|archive\s+document|bundesarchiv|wikisource)\b",
    re.I,
)
_NON_PRODUCT_TITLE_RE = re.compile(
    r"\b(suche\s+wohnung|wohnung\s+gesucht|(?:\d+\s*)?zimmer\s+wohnung|\bwohnung\b|von\s+privat|"
    r"hulp\s+aan\s+huis|aan\s+huis|voorrijkosten|geen\s+voorrijkosten|"
    r"mark[- ]?\s*och\s+grundarbete|arbete\s+utf[oö]rs|repair\s+service|reparatie|service\s+aan\s+huis|"
    r"pokoje\s+noclegi|noclegi|domki\s+z\s+kominkiem|kominkiem\s+i\s+widokiem|sauna\s+spa|"
    r"koci\s+idea[lł]|kocia\s+idea[lł]|czeka\s+na\s+sw[oó]j\s+dom|czeka\s+na\s+swoj\s+dom|"
    r"oddam\s+za\s+darmo|do\s+adopcji|adopcja|^\s*s[øo]ger\s*:)\b",
    re.I,
)
_AI_EDGE_CATALOG_MIN_CONFIDENCE = 0.93
_CATALOG_CATEGORY_SUPPORT_RE: dict[str, re.Pattern] = {
    "technology_smartphone": re.compile(r"\b(iphone|smartphone|cellulare|telefono|pixel\s+\d|google\s+pixel|galaxy\s+(?:s|z|a)\d|xiaomi|redmi|oneplus|mobile\s+phone)\b", re.I),
    "technology_ram": re.compile(r"\b(ram|ddr[345]|so-?dimm|sodimm|dimm|arbeitsspeicher|memoria\s+ram|memory\s+ram)\b", re.I),
    "technology_server_parts": re.compile(r"\b(server\s+(?:part|parts|component|drive|cage|backplane)|serverlama|proliant|poweredge|dl3[68]0|dl380|r7[34]0|drive\s+cage|backplane|raid\s+controller|\bhba\b|\bpdu\b|network\s+switch|switch\s+ethernet)\b", re.I),
    "technology_smartwatch": re.compile(r"\b(smartwatch|smart\s+watch|apple\s+watch|galaxy\s+watch|orologio\s+smart|[aä]lykello)\b", re.I),
    "technology_camera": re.compile(r"\b(camera|kamera|fotocamera|videokamera|action\s+camera|lens|lente|objektiivi|objective|gorillapod|tripod|kugelkopf|leica|panasonic|canon|nikon|sony\s+alpha)\b", re.I),
    "technology_storage": re.compile(r"\b(ssd|nvme|m\.?2|hard\s+disk|hard\s+drive|hdd|solid[- ]state|festplatte|disque\s+ssd|dysk\s+ssd)\b", re.I),
    "technology_laptop": re.compile(r"\b(laptop|notebook|thinkpad|latitude|elitebook|zbook|macbook|laptopscherm|laptop\s+screen)\b", re.I),
    "technology_monitor": re.compile(r"\b(monitor|beeldscherm|bildschirm|schermo|display|televis(?:ie|ies)|tv|oled|qled|wqhd|qhd|uhd|4k)\b", re.I),
    "technology_audio_speakers": re.compile(r"\b(speakers?|luidspreker|luidsprekers|lautsprecher|casse\s+audio|altoparlanti|soundbar|soundtouch)\b", re.I),
    "technology_audio_amplifier": re.compile(r"\b(amplificatore|amplificador|amplifier|verst[aä]rker|receiver|pedalera|hb-40r|hifi\s+amplifier)\b", re.I),
    "technology_audio_headphones": re.compile(r"\b(cuffie|auricolari|headphones?|headset|hoofdtelefoons?|koptelefoon|kopfh[oö]rer|airpods|earbuds?)\b", re.I),
    "technology_audio_turntable": re.compile(r"\b(giradischi|turntable|record\s+player|platenspeler|plattenspieler|tocadiscos|tourne[- ]disque|vinyl\s+player)\b", re.I),
    "technology_accessory": re.compile(r"\b(usb-?c|hdmi|ethernet|lan\s+cable|netwerkkabels?|charger|caricatore|charging\s+cable|cavo|cavi|adapter|adapters?|cover|custodia|screen\s+protector|hub|dock|docking\s+station|laptopscherm|laptop\s+screen)\b", re.I),
    "technology_tablet": re.compile(r"\b(ipad|tablet|galaxy\s+tab|surface\s+pro|tab\s+s\d+)\b", re.I),
    "technology_gpu": re.compile(r"\b(rtx|gtx|radeon|quadro|gpu|scheda\s+video|graphics\s+card|vram|gddr)\b", re.I),
    "technology_console": re.compile(r"\b(console|playstation|ps[2345]|xbox|nintendo\s+switch|steam\s+deck|spelcomputer|mario\s+kart)\b", re.I),
    "vehicle_car_part": re.compile(r"\b(ricambio\s+auto|car\s+part|auto\s+part|pezzo\s+auto|autoteile|ersatzteil|teile|cz[eę]ści\s+samochodowe|czesci\s+samochodowe|kompresor\s+klimatyzacji|klimakompressor|felgenschloss|paraurti|bumper|otomoto|p[oó]łki\s+tylne|polki\s+tylne|audi|bmw|opel|astra|range\s+rover|evoque)\b", re.I),
    "technology_keyboard": re.compile(r"\b(keyboard|gaming\s+keyboard|toetsenbord|tastiera|tastatur|clavier|teclado)\b", re.I),
    "technology_printer": re.compile(r"\b(printer|print\s*&\s*cut|stampante|drukarka|drucker|imprimante|impresora|barcode\s+scanner|scanner|ls2208|bn-20)\b", re.I),
    "fashion_clothing": re.compile(r"\b(clothing|abbigliamento|vestiti|kleidung|kleding|ropa|odzie[zż]|shirt|t-?shirt|polo|maglia|camicia|chaqueta|giacca|morgenmantel|bata|scarpe|shoes|sneakers?|adidas|asics|ralph\s+lauren|h&m|c\.?p\.?\s+company|cp\s+company|ragno)\b", re.I),
    "home_furniture_table": re.compile(r"\b(tavolo|dining\s+table|coffee\s+table|tisch|tafel|p[oö]yt[aä]|neuvottelup[oö]yt[aä]|palettentisch|balkonm[oö]bel|gartenm[oö]bel)\b", re.I),
    "home_furniture_chair": re.compile(r"\b(sedia|chair|chairs|stuhl|stühle|stuhle|sessel|chaise|silla|krzeslo|krzesło|tuoli|hocker|sgabello|istuinkoroke)\b", re.I),
    "home_decor_photo_frame": re.compile(r"\b(photo\s+frame|picture\s+frame|fotolijst|fotolijsten|cornice|cornici|bilderrahmen|cadre\s+photo|marco\s+de\s+fotos)\b", re.I),
    "home_decor_wall_art": re.compile(r"\b(wall\s+art|poster|quadro|painting|dipinto|bild|wandbild|kunstdruck|tableau|cuadro|obraz|plakat)\b", re.I),
}
_CATALOG_TECH_POISON_NEGATIVE_RE = re.compile(
    r"\b(louis\s+vuitton|monogram|porte\s+documents|retro\s+kontors|inredning|k[oø]kken|hylde|gardiner|"
    r"umkleidekabine|wohnung|morgenmantel|reithose|schlafsofa|sofa|sessel|clarinete|pickup|hundk[aå]pa|arbetsk[aå]pa|viltfoder|h[öo]silage|terrassevarmer|audemars|piguet|f\u00fcrstenberg|forstenberg)\b",
    re.I,
)



_CATALOG_RAM_MEMORY_STRONG_RE = re.compile(r"\b(ddr[345]|so-?dimm|sodimm|dimm|arbeitsspeicher|memoria\s+ram|memory\s+ram|\d+\s*gb\s+(?:ram|memory)|ram\s+\d+\s*gb)\b", re.I)
_CATALOG_RAM_FALSE_CONTEXT_RE = re.compile(r"\b(pickup|crew\s+1500|dodge\s+ram|hundk[aå]pa|arbetsk[aå]pa|dubbelbur|dog\s+cage|hundbur)\b", re.I)
_CATALOG_SERVER_PART_STRONG_RE = re.compile(r"\b(server\s+(?:part|parts|component|drive|cage|backplane)|serverlama|proliant|poweredge|dl3[68]0|dl380|r7[34]0|drive\s+cage|backplane|raid\s+controller|\bhba\b|\bpdu\b|network\s+switch|switch\s+ethernet)\b", re.I)
_CATALOG_SERVER_PART_FALSE_CONTEXT_RE = re.compile(r"\b(viltfoder|h[öo]silage|sm[aå]bal|smabal|foder|haylage|feed|bale|terrassevarmer|gas\s+i\s+rustfrit|gas\s+heater|patio\s+heater|varmer)\b", re.I)
_CATALOG_SMARTWATCH_STRONG_RE = re.compile(r"\b(smartwatch|smart\s+watch|apple\s+watch|galaxy\s+watch|orologio\s+smart|[aä]lykello)\b", re.I)
_CATALOG_CAMERA_STRONG_RE = re.compile(r"\b(camera|kamera|fotocamera|videokamera|action\s+camera|lens|lente|objektiivi|objective|gorillapod|tripod|kugelkopf|leica|panasonic|canon|nikon|sony\s+alpha)\b", re.I)
_CATALOG_PHOTO_FRAME_STRONG_RE = re.compile(r"\b(photo\s+frame|picture\s+frame|fotolijst|fotolijsten|cornice|cornici|bilderrahmen|cadre\s+photo|marco\s+de\s+fotos)\b", re.I)
_CATALOG_WALL_ART_STRONG_RE = re.compile(r"\b(wall\s+art|poster|quadro|painting|dipinto|bild|wandbild|kunstdruck|tableau|cuadro|obraz|plakat)\b", re.I)
_CATALOG_HOME_DECOR_FALSE_CONTEXT_RE = re.compile(r"\b(casa\s+con\s+veranda|veranda|camera\s+da\s+letto|bedroom|noclegi|casa\s+residenziale|house|domki|orologio|watch|wristwatch|audemars|piguet)\b", re.I)
_CATALOG_CAR_PART_FALSE_CONTEXT_RE = re.compile(r"\b(wmf|spiralschneider|k[üu]chenger[aä]te|kuechengeraete|gem[üu]se|gemuese|zucchini|kartoffel|kult\s+pro|sigillante|sealant|impermeabile|mr\s+seal|camper\s+e\s+casa)\b", re.I)
_CATALOG_WHOLE_CAR_FALSE_CONTEXT_RE = re.compile(r"\b(imbarcazione|barca|boat|motorboat|sporty\s+wodne|maszyna\s+rolnicza|rolnicz|zbo[żz]a|harvester|kombajn|trattore|agricultural\s+machine|camper\s+e\s+casa|sigillante|sealant)\b", re.I)

_CATALOG_GAME_MEDIA_NOT_CONSOLE_RE = re.compile(
    r"\b(games?|giochi|spellen|toptitels|game\s+lot|game\s+collection)\b",
    re.I,
)
_CATALOG_CONSOLE_HARDWARE_RE = re.compile(
    r"\b(console|spelcomputer|nintendo\s+switch|switch\s+console|steam\s+deck|controller|gamepad|joy-?con|lenkrad|wheel|pedals?|pedalen|system|hardware|console\s+bundle)\b",
    re.I,
)
_CATALOG_KITCHEN_OR_HOUSEHOLD_NON_VEHICLE_RE = re.compile(
    r"\b(wmf|spiralschneider|k[üu]chenger[aä]te|kuechengeraete|gem[üu]se|gemuese|zucchini|kartoffel|kult\s+pro|sauna|filmprojektor|bildprojektor|sigillante|sealant|impermeabile|mr\s+seal|camper\s+e\s+casa)\b",
    re.I,
)

# M9.7.24: catalog learning must validate against the real listing title,
# not against synthetic canonical seeds such as 'game console Sony' or
# 'graphics card Apple ID'.  These patterns are intentionally strict.
_CATALOG_REQUEST_OR_WANTED_RE = re.compile(
    r"\b(s[øo]ger\s*:|s[øo]ger\b|suche\b|gesucht\b|wanted\b|looking\s+for\b|cerco\b)",
    re.I,
)
_CATALOG_STRONG_CONSOLE_HARDWARE_RE = re.compile(
    r"\b(console\b|spelcomputer|nintendo\s+switch(?!\s+hori)|switch\s+console|steam\s+deck|playstation\s*5\b|\bps5\b|playstation\s*4\s+console|\bps4\s+console|xbox\s+(?:one|series|360)\s+console|nes\s+nintendo\s+classic\s+mini)\b",
    re.I,
)
_CATALOG_CONSOLE_FALSE_CONTEXT_RE = re.compile(
    r"\b(games?|giochi|spellen|toptitels|game\s+lot|game\s+collection|mixtape|windows\s+pc|controller|gamepad|headset|hoofdtelefoons?|koptelefoon|logitech\s+a50|hori|lenkrad|wheel|pedals?|pedalen)\b",
    re.I,
)
_CATALOG_GPU_FALSE_CONTEXT_RE = re.compile(r"\b(macbook|iphone|ipad|apple\s+id|smartphone|tablet)\b", re.I)
_CATALOG_STRONG_WHOLE_CAR_RE = re.compile(
    r"\b(bmw|audi|mercedes|volkswagen|\bvw\b|fiat|ford|toyota|tesla|renault\s+trafic|renault|peugeot|citroen|opel|astra|range\s+rover|land\s+rover|seria\s+5|serie\s+5|golf|passat|polo|clio|megane|diesel|benzina|automatic|automatik|manuale|\bez\s*\d{2,4}\b)\b",
    re.I,
)
_CATALOG_GENERIC_WHOLE_CAR_SEED_RE = re.compile(r"^\s*car(?:\s+(?:ez|nur|of)\s*\d+)?\s*$", re.I)
_CATALOG_GENERIC_TECH_SEED_RE = re.compile(
    r"^\s*(?:game\s+console(?:\s+(?:sony|xbox\s*360|n64|uhr\s*\d+|logitech\s+a50))?|graphics\s+card\s+apple\s+id\s*\d+|smartphone\s+uhr\s*\d+|smartwatch\s+apple\s+norm\s*\d+|speakers\s+yamaha\s+s701)\s*$",
    re.I,
)

def _canonical_category_key(value) -> str:
    raw = re.sub(r"\s+", " ", str(value or "")).strip()
    if not raw or raw.lower() in {"unknown", "none", "null", "na", "n/a", "vehicle_car_weak"}:
        return ""
    raw = _CATEGORY_ALIASES.get(raw, raw)
    if raw in _VALID_CATALOG_CATEGORY_KEYS:
        return raw
    simplified = _ICON_NOISE_RE.sub("", raw).strip()
    simplified = _CATEGORY_ALIASES.get(simplified, simplified)
    if simplified in _VALID_CATALOG_CATEGORY_KEYS:
        return simplified
    for candidate in (canonical_category_from_title("", simplified), canonical_category_from_title(simplified, "")):
        candidate = _CATEGORY_ALIASES.get(re.sub(r"\s+", " ", str(candidate or "")).strip(), re.sub(r"\s+", " ", str(candidate or "")).strip())
        if candidate in _VALID_CATALOG_CATEGORY_KEYS and candidate != "unknown":
            return candidate
    return ""


def _safe_json_object(value) -> dict:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()




_WEAK_WHOLE_VEHICLE_RE = re.compile(
    r"\b(automobile|voiture|coche|samoch(?:o|ó)d|gebrauchtwagen|used\s+car|auto\s+usata|auto\s+nuova|\bcar\b|\bcars\b)\b",
    re.I,
)
_WEAK_VEHICLE_FALSE_POSITIVE_RE = re.compile(
    r"\b(cavo|usb[- ]?c|caricatore|charger|charging|cover|case|custodia|pellicola|dock|hub|"
    r"biljardbord|billiard|pool\s+table|wobbler|fishing\s+lure|lego|school\s+bag|skoletaske|"
    r"ba[uú]l\s+de\s+moto|baule\s+moto|top\s*case|istuinkoroke|turvaistuimet|imbarcazione|barca|boat|maszyna\s+rolnicza|rolnicz|zbo[żz]a|sigillante|sealant|mr\s+seal)\b",
    re.I,
)



def _title_category_overrides_evidence(title_category: str, evidence_category: str, text: str) -> bool:
    title_category = _canonical_category_key(title_category)
    evidence_category = _canonical_category_key(evidence_category)
    if not title_category or not evidence_category or title_category == evidence_category:
        return False
    # Never let title-only whole-car inference erase stronger part/accessory evidence.
    if title_category == "vehicle_car" and evidence_category in {"vehicle_car_part", "vehicle_motorcycle_accessory"}:
        return False
    if title_category in _STRONG_TITLE_OVERRIDE_CATEGORIES:
        return True
    # Known poison pairs from stale source categories / weak online query hints.
    if evidence_category in {"technology_smartphone", "technology_ram", "technology_audio_amplifier", "technology_laptop", "technology_monitor"}:
        if title_category and title_category != evidence_category:
            return True
    return False

def _vehicle_category_is_weak(category: str, source: str, confidence: float, title: str, original_category: str) -> bool:
    """Return True when vehicle_car came from weak marketplace noise, not a whole-car signal.

    M9.7.24 tightened this: generic words like "car", "automobile" or
    category pages such as gebrauchtewagenboerse are not enough to create a
    catalog family.  We require a make/model-like signal, or strong AI/research
    evidence that still contains such a signal.
    """
    if category != "vehicle_car":
        return False
    hay = f"{title or ''} {original_category or ''}"
    if _WEAK_VEHICLE_FALSE_POSITIVE_RE.search(hay) or _CATALOG_WHOLE_CAR_FALSE_CONTEXT_RE.search(hay):
        return True
    if _CATALOG_GENERIC_WHOLE_CAR_SEED_RE.search(str(title or "")):
        return True
    if _CATALOG_STRONG_WHOLE_CAR_RE.search(hay):
        return False
    # Generic marketplace category words are weak without a model/brand-like clue.
    return True


def _category_supported_by_catalog_title(category: str, text: str) -> bool:
    category = _canonical_category_key(category)
    text = str(text or "")
    if _CATALOG_REQUEST_OR_WANTED_RE.search(text):
        return False
    if _CATALOG_GENERIC_TECH_SEED_RE.search(text):
        return False
    if category == "technology_console":
        if _CATALOG_CONSOLE_FALSE_CONTEXT_RE.search(text):
            return False
        return bool(_CATALOG_STRONG_CONSOLE_HARDWARE_RE.search(text))
    if category == "technology_gpu":
        if _CATALOG_GPU_FALSE_CONTEXT_RE.search(text):
            return False
        pattern = _CATALOG_CATEGORY_SUPPORT_RE.get(category)
        return bool(pattern and pattern.search(text))
    if category == "vehicle_car":
        if _CATALOG_WHOLE_CAR_FALSE_CONTEXT_RE.search(text) or _CATALOG_GENERIC_WHOLE_CAR_SEED_RE.search(text):
            return False
        return bool(_CATALOG_STRONG_WHOLE_CAR_RE.search(text))
    if category == "technology_ram":
        if _CATALOG_RAM_FALSE_CONTEXT_RE.search(text):
            return False
        return bool(_CATALOG_RAM_MEMORY_STRONG_RE.search(text))
    if category == "technology_server_parts":
        if _CATALOG_SERVER_PART_FALSE_CONTEXT_RE.search(text):
            return False
        return bool(_CATALOG_SERVER_PART_STRONG_RE.search(text))
    if category == "technology_smartwatch":
        return bool(_CATALOG_SMARTWATCH_STRONG_RE.search(text))
    if category == "technology_audio_speakers":
        # Avoid Yamaha A-S701 / amplifier category bleed into speakers.
        if re.search(r"\b(amplifier|amplificatore|amplificador|verst[aä]rker|receiver|ontvangers|versterkers|a-?s701|s701)\b", text, re.I):
            return False
    if category == "technology_camera":
        return bool(_CATALOG_CAMERA_STRONG_RE.search(text))
    if category == "vehicle_car_part":
        if _CATALOG_KITCHEN_OR_HOUSEHOLD_NON_VEHICLE_RE.search(text) or _CATALOG_CAR_PART_FALSE_CONTEXT_RE.search(text):
            pattern = _CATALOG_CATEGORY_SUPPORT_RE.get(category)
            return bool(pattern and pattern.search(text))
    if category == "home_decor_photo_frame":
        return bool(_CATALOG_PHOTO_FRAME_STRONG_RE.search(text)) and not bool(_CATALOG_HOME_DECOR_FALSE_CONTEXT_RE.search(text))
    if category == "home_decor_wall_art":
        return bool(_CATALOG_WALL_ART_STRONG_RE.search(text)) and not bool(_CATALOG_HOME_DECOR_FALSE_CONTEXT_RE.search(text))
    if category in {"home_furniture_table", "home_furniture_chair"} and _UNSUPPORTED_DOCUMENT_TITLE_RE.search(text):
        return False
    pattern = _CATALOG_CATEGORY_SUPPORT_RE.get(category)
    if not pattern:
        return True
    return bool(pattern.search(text))


def _research_category_is_title_unsupported(category: str, source: str, confidence: float, text: str) -> bool:
    category = _canonical_category_key(category)
    if source not in {"online_product_research", "multilingual_normalization"}:
        return False
    if not category:
        return False
    if _NON_PRODUCT_TITLE_RE.search(text or "") or _UNSUPPORTED_DOCUMENT_TITLE_RE.search(text or ""):
        return True
    if category.startswith("technology_") and _CATALOG_TECH_POISON_NEGATIVE_RE.search(text or "") and not _category_supported_by_catalog_title(category, text):
        return True
    # For tech categories we know how to validate, require real title support.
    if category in _CATALOG_CATEGORY_SUPPORT_RE and not _category_supported_by_catalog_title(category, text):
        return True
    return False


class MarketplaceCacheStore:
    """SQLite cache for long-running marketplace/catalog harvesting."""

    def __init__(self, path: str | Path = "data/marketplace_cache/marketplace.sqlite"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.init_schema()
        try:
            self.seed_default_categories()
        except Exception:
            pass

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS category_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_key TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                parent_key TEXT,
                group_name TEXT,
                keywords_json TEXT,
                profiles_json TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS source_category_map (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                category_key TEXT NOT NULL,
                source_category_id TEXT,
                source_category_label TEXT,
                source_category_url TEXT,
                confidence REAL NOT NULL DEFAULT 0.5,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_source_category_map_unique_expr
            ON source_category_map(source, category_key, COALESCE(source_category_id, ''), COALESCE(source_category_url, ''));

            CREATE TABLE IF NOT EXISTS search_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                profile TEXT,
                source TEXT,
                query TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                message TEXT
            );

            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                external_id TEXT,
                url TEXT,
                title TEXT NOT NULL,
                price REAL,
                currency TEXT,
                location TEXT,
                seller TEXT,
                condition TEXT,
                image_url TEXT,
                category TEXT,
                query TEXT,
                specs_json TEXT,
                raw_json TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER NOT NULL,
                run_id INTEGER,
                seen_at TEXT NOT NULL,
                price REAL,
                currency TEXT,
                query TEXT,
                FOREIGN KEY(listing_id) REFERENCES listings(id),
                FOREIGN KEY(run_id) REFERENCES search_runs(id)
            );


            CREATE TABLE IF NOT EXISTS product_families (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                brand TEXT,
                family_name TEXT NOT NULL,
                family_key TEXT NOT NULL UNIQUE,
                confidence REAL NOT NULL DEFAULT 0.5,
                metadata_json TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS product_variants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family_id INTEGER NOT NULL,
                variant_key TEXT NOT NULL UNIQUE,
                variant_name TEXT NOT NULL,
                variant_label TEXT,
                confidence REAL NOT NULL DEFAULT 0.5,
                ambiguity_status TEXT NOT NULL DEFAULT 'resolved',
                metadata_json TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                FOREIGN KEY(family_id) REFERENCES product_families(id)
            );

            CREATE TABLE IF NOT EXISTS product_identifiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family_id INTEGER,
                variant_id INTEGER,
                identifier_type TEXT NOT NULL,
                identifier_value TEXT NOT NULL,
                source TEXT,
                confidence REAL NOT NULL DEFAULT 0.5,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                UNIQUE(identifier_type, identifier_value, source),
                FOREIGN KEY(family_id) REFERENCES product_families(id),
                FOREIGN KEY(variant_id) REFERENCES product_variants(id)
            );

            CREATE TABLE IF NOT EXISTS product_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family_id INTEGER,
                variant_id INTEGER,
                alias TEXT NOT NULL,
                alias_norm TEXT NOT NULL,
                source TEXT,
                confidence REAL NOT NULL DEFAULT 0.5,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                UNIQUE(alias_norm, source),
                FOREIGN KEY(family_id) REFERENCES product_families(id),
                FOREIGN KEY(variant_id) REFERENCES product_variants(id)
            );

            CREATE TABLE IF NOT EXISTS spec_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family_id INTEGER,
                variant_id INTEGER,
                spec_key TEXT NOT NULL,
                spec_value_json TEXT NOT NULL,
                unit TEXT,
                source TEXT,
                confidence REAL NOT NULL DEFAULT 0.5,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                FOREIGN KEY(family_id) REFERENCES product_families(id),
                FOREIGN KEY(variant_id) REFERENCES product_variants(id)
            );

            CREATE TABLE IF NOT EXISTS listing_variant_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER NOT NULL,
                variant_id INTEGER,
                family_id INTEGER,
                score REAL NOT NULL DEFAULT 0.5,
                reason TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(listing_id) REFERENCES listings(id),
                FOREIGN KEY(variant_id) REFERENCES product_variants(id),
                FOREIGN KEY(family_id) REFERENCES product_families(id)
            );




            CREATE TABLE IF NOT EXISTS listing_online_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                query TEXT,
                confidence REAL,
                reason TEXT,
                evidence_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(listing_id)
            );

            CREATE INDEX IF NOT EXISTS idx_listing_online_verifications_status ON listing_online_verifications(status);
            CREATE INDEX IF NOT EXISTS idx_listing_online_verifications_listing_id ON listing_online_verifications(listing_id);


            CREATE TABLE IF NOT EXISTS listing_cleaning_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER NOT NULL,
                stage TEXT NOT NULL DEFAULT 'pending',
                decision TEXT,
                confidence REAL,
                reason TEXT,
                normalized_title TEXT,
                normalized_category TEXT,
                ai_response TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(listing_id)
            );

            CREATE INDEX IF NOT EXISTS idx_listing_cleaning_reviews_stage ON listing_cleaning_reviews(stage);
            CREATE INDEX IF NOT EXISTS idx_listing_cleaning_reviews_listing_id ON listing_cleaning_reviews(listing_id);


            CREATE TABLE IF NOT EXISTS listing_multilingual_normalizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER NOT NULL UNIQUE,
                source TEXT NOT NULL,
                method TEXT NOT NULL,
                language_detected TEXT,
                language_confidence REAL,
                title_original TEXT,
                resolved_title TEXT,
                title_it TEXT,
                title_en TEXT,
                title_it_hint TEXT,
                title_en_hint TEXT,
                title_search_normalized TEXT,
                category_original TEXT,
                category_canonical TEXT,
                category_family TEXT,
                product_type_canonical TEXT,
                brand TEXT,
                model TEXT,
                aliases_json TEXT,
                matched_aliases_json TEXT,
                confidence REAL,
                evidence_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(listing_id) REFERENCES listings(id)
            );

            CREATE INDEX IF NOT EXISTS idx_lmn_source ON listing_multilingual_normalizations(source);
            CREATE INDEX IF NOT EXISTS idx_lmn_language ON listing_multilingual_normalizations(language_detected);
            CREATE INDEX IF NOT EXISTS idx_lmn_category ON listing_multilingual_normalizations(category_canonical);
            CREATE INDEX IF NOT EXISTS idx_lmn_product_type ON listing_multilingual_normalizations(product_type_canonical);


            CREATE TABLE IF NOT EXISTS listing_online_product_research (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER NOT NULL UNIQUE,
                source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                query TEXT,
                found_sources_json TEXT,
                canonical_title TEXT,
                canonical_brand TEXT,
                canonical_model TEXT,
                canonical_category TEXT,
                category_family TEXT,
                product_type TEXT,
                aliases_json TEXT,
                evidence_snippets_json TEXT,
                confidence REAL,
                reason TEXT,
                diagnostics_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(listing_id) REFERENCES listings(id)
            );

            CREATE INDEX IF NOT EXISTS idx_lopr_status ON listing_online_product_research(status);
            CREATE INDEX IF NOT EXISTS idx_lopr_source ON listing_online_product_research(source);
            CREATE INDEX IF NOT EXISTS idx_lopr_listing_id ON listing_online_product_research(listing_id);
            CREATE INDEX IF NOT EXISTS idx_lopr_category ON listing_online_product_research(canonical_category);


            CREATE TABLE IF NOT EXISTS listing_ai_edge_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER NOT NULL UNIQUE,
                source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                trigger_reason TEXT,
                input_title TEXT,
                input_category TEXT,
                input_image_url TEXT,
                vision_used INTEGER NOT NULL DEFAULT 0,
                vision_summary TEXT,
                canonical_title TEXT,
                canonical_brand TEXT,
                canonical_model TEXT,
                canonical_category TEXT,
                category_family TEXT,
                product_type TEXT,
                confidence REAL,
                reason TEXT,
                raw_response_json TEXT,
                diagnostics_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(listing_id) REFERENCES listings(id)
            );

            CREATE INDEX IF NOT EXISTS idx_ai_edge_status ON listing_ai_edge_reviews(status);
            CREATE INDEX IF NOT EXISTS idx_ai_edge_source ON listing_ai_edge_reviews(source);
            CREATE INDEX IF NOT EXISTS idx_ai_edge_listing_id ON listing_ai_edge_reviews(listing_id);
            CREATE INDEX IF NOT EXISTS idx_ai_edge_category ON listing_ai_edge_reviews(canonical_category);


            CREATE TABLE IF NOT EXISTS crawl_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                task_kind TEXT NOT NULL,
                task_key TEXT NOT NULL,
                category_path TEXT,
                url TEXT,
                status TEXT NOT NULL,
                message TEXT,
                saved_count INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                finished_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(source, task_kind, task_key)
            );

            CREATE INDEX IF NOT EXISTS idx_crawl_checkpoints_status ON crawl_checkpoints(status);
            CREATE INDEX IF NOT EXISTS idx_crawl_checkpoints_source ON crawl_checkpoints(source);

            CREATE TABLE IF NOT EXISTS product_conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family_id INTEGER,
                variant_id INTEGER,
                listing_id INTEGER,
                conflict_key TEXT NOT NULL,
                claimed_value_json TEXT,
                canonical_value_json TEXT,
                source TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                FOREIGN KEY(family_id) REFERENCES product_families(id),
                FOREIGN KEY(variant_id) REFERENCES product_variants(id),
                FOREIGN KEY(listing_id) REFERENCES listings(id)
            );

            CREATE INDEX IF NOT EXISTS idx_product_families_category ON product_families(category);
            CREATE INDEX IF NOT EXISTS idx_product_variants_family ON product_variants(family_id);
            CREATE INDEX IF NOT EXISTS idx_spec_facts_key ON spec_facts(spec_key);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_spec_facts_unique_expr
            ON spec_facts(COALESCE(variant_id, -1), COALESCE(family_id, -1), spec_key, spec_value_json, COALESCE(source, ''));
            CREATE INDEX IF NOT EXISTS idx_product_identifiers_value ON product_identifiers(identifier_value);
            CREATE INDEX IF NOT EXISTS idx_listing_variant_candidates_listing ON listing_variant_candidates(listing_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_listing_candidates_unique_expr
            ON listing_variant_candidates(listing_id, COALESCE(variant_id, -1), COALESCE(family_id, -1));

            CREATE INDEX IF NOT EXISTS idx_category_nodes_key ON category_nodes(category_key);
            CREATE INDEX IF NOT EXISTS idx_source_category_map_source ON source_category_map(source);
            CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source);
            CREATE INDEX IF NOT EXISTS idx_listings_query ON listings(query);
            CREATE INDEX IF NOT EXISTS idx_listings_last_seen ON listings(last_seen);
            CREATE INDEX IF NOT EXISTS idx_observations_listing ON observations(listing_id);
            """
        )
        self.conn.commit()

    def start_run(self, *, profile: str, source: str, query: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO search_runs(started_at, profile, source, query, status) VALUES (?, ?, ?, ?, ?)",
            (utc_now_iso(), profile, source, query, "running"),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, *, status: str = "ok", message: str = "") -> None:
        self.conn.execute(
            "UPDATE search_runs SET finished_at=?, status=?, message=? WHERE id=?",
            (utc_now_iso(), status, message, run_id),
        )
        self.conn.commit()

    def upsert_listing(self, listing: HarvestListing, *, run_id: int | None = None, auto_catalog: bool = True) -> int:
        now = utc_now_iso()
        fingerprint = listing.fingerprint()
        specs_json = json.dumps(listing.specs or {}, ensure_ascii=False, sort_keys=True)
        raw_json = json.dumps(listing.raw or {}, ensure_ascii=False, sort_keys=True)

        existing = self.conn.execute(
            "SELECT id, seen_count FROM listings WHERE fingerprint=?",
            (fingerprint,),
        ).fetchone()

        if existing:
            listing_id = int(existing["id"])
            self.conn.execute(
                """
                UPDATE listings
                SET last_seen=?,
                    seen_count=?,
                    price=COALESCE(?, price),
                    currency=COALESCE(NULLIF(?, ''), currency),
                    title=COALESCE(NULLIF(?, ''), title),
                    url=COALESCE(NULLIF(?, ''), url),
                    image_url=COALESCE(NULLIF(?, ''), image_url),
                    query=COALESCE(NULLIF(?, ''), query),
                    specs_json=CASE WHEN ? != '{}' THEN ? ELSE specs_json END,
                    raw_json=CASE WHEN ? != '{}' THEN ? ELSE raw_json END
                WHERE id=?
                """,
                (
                    now,
                    int(existing["seen_count"]) + 1,
                    listing.price,
                    listing.currency,
                    listing.title,
                    listing.url,
                    listing.image_url,
                    listing.query,
                    specs_json,
                    specs_json,
                    raw_json,
                    raw_json,
                    listing_id,
                ),
            )
        else:
            cur = self.conn.execute(
                """
                INSERT INTO listings (
                    fingerprint, source, external_id, url, title, price, currency, location,
                    seller, condition, image_url, category, query, specs_json, raw_json,
                    first_seen, last_seen, seen_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    fingerprint,
                    listing.source,
                    listing.external_id,
                    listing.url,
                    listing.title,
                    listing.price,
                    listing.currency,
                    listing.location,
                    listing.seller,
                    listing.condition,
                    listing.image_url,
                    listing.category,
                    listing.query,
                    specs_json,
                    raw_json,
                    now,
                    now,
                ),
            )
            listing_id = int(cur.lastrowid)

        self.conn.execute(
            """
            INSERT INTO observations(listing_id, run_id, seen_at, price, currency, query)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (listing_id, run_id, now, listing.price, listing.currency, listing.query),
        )
        if auto_catalog:
            try:
                from .catalog import upsert_catalog_from_listing
                upsert_catalog_from_listing(self, listing, listing_id=listing_id)
            except Exception:
                pass

        self.conn.commit()
        return listing_id


    def upsert_product_family(self, *, category: str, brand: str, family_name: str, family_key: str, confidence: float = 0.5, metadata: dict | None = None) -> int:
        now = utc_now_iso(); metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
        existing = self.conn.execute("SELECT id FROM product_families WHERE family_key=?", (family_key,)).fetchone()
        if existing:
            family_id = int(existing["id"])
            self.conn.execute("UPDATE product_families SET last_seen=?, confidence=MAX(confidence, ?), metadata_json=CASE WHEN ? != '{}' THEN ? ELSE metadata_json END WHERE id=?", (now, confidence, metadata_json, metadata_json, family_id))
            return family_id
        cur = self.conn.execute("INSERT INTO product_families(category, brand, family_name, family_key, confidence, metadata_json, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (category, brand, family_name, family_key, confidence, metadata_json, now, now))
        return int(cur.lastrowid)

    def upsert_product_variant(self, *, family_id: int, variant_key: str, variant_name: str, variant_label: str = "", confidence: float = 0.5, ambiguity_status: str = "resolved", metadata: dict | None = None) -> int:
        now = utc_now_iso(); metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
        existing = self.conn.execute("SELECT id FROM product_variants WHERE variant_key=?", (variant_key,)).fetchone()
        if existing:
            variant_id = int(existing["id"])
            self.conn.execute("UPDATE product_variants SET last_seen=?, confidence=MAX(confidence, ?), ambiguity_status=?, metadata_json=CASE WHEN ? != '{}' THEN ? ELSE metadata_json END WHERE id=?", (now, confidence, ambiguity_status, metadata_json, metadata_json, variant_id))
            return variant_id
        cur = self.conn.execute("INSERT INTO product_variants(family_id, variant_key, variant_name, variant_label, confidence, ambiguity_status, metadata_json, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (family_id, variant_key, variant_name, variant_label, confidence, ambiguity_status, metadata_json, now, now))
        return int(cur.lastrowid)

    def upsert_product_identifier(self, *, family_id: int | None, variant_id: int | None, identifier_type: str, identifier_value: str, source: str = "", confidence: float = 0.5) -> int:
        now = utc_now_iso(); src = source or ""
        existing = self.conn.execute("SELECT id FROM product_identifiers WHERE identifier_type=? AND identifier_value=? AND COALESCE(source, '')=?", (identifier_type, identifier_value, src)).fetchone()
        if existing:
            iid = int(existing["id"])
            self.conn.execute("UPDATE product_identifiers SET last_seen=?, confidence=MAX(confidence, ?), family_id=COALESCE(family_id, ?), variant_id=COALESCE(variant_id, ?) WHERE id=?", (now, confidence, family_id, variant_id, iid))
            return iid
        cur = self.conn.execute("INSERT INTO product_identifiers(family_id, variant_id, identifier_type, identifier_value, source, confidence, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (family_id, variant_id, identifier_type, identifier_value, src, confidence, now, now))
        return int(cur.lastrowid)

    @staticmethod
    def _alias_norm(alias: str) -> str:
        import re
        text = str(alias or "").lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def upsert_product_alias(self, *, family_id: int | None, variant_id: int | None, alias: str, source: str = "", confidence: float = 0.5) -> int | None:
        alias = str(alias or "").strip()
        alias_norm = self._alias_norm(alias)
        if not alias_norm or len(alias_norm) < 2:
            return None
        now = utc_now_iso(); src = source or ""
        existing = self.conn.execute(
            "SELECT id FROM product_aliases WHERE alias_norm=? AND COALESCE(source, '')=?",
            (alias_norm, src),
        ).fetchone()
        if existing:
            aid = int(existing["id"])
            self.conn.execute(
                """
                UPDATE product_aliases
                SET last_seen=?,
                    confidence=MAX(confidence, ?),
                    family_id=COALESCE(family_id, ?),
                    variant_id=COALESCE(variant_id, ?)
                WHERE id=?
                """,
                (now, confidence, family_id, variant_id, aid),
            )
            return aid
        cur = self.conn.execute(
            """
            INSERT INTO product_aliases(family_id, variant_id, alias, alias_norm, source, confidence, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (family_id, variant_id, alias, alias_norm, src, confidence, now, now),
        )
        return int(cur.lastrowid)

    def upsert_spec_fact(self, *, family_id: int | None, variant_id: int | None, spec_key: str, spec_value, unit: str = "", source: str = "", confidence: float = 0.5) -> int:
        now = utc_now_iso(); src = source or ""; value_json = json.dumps(spec_value, ensure_ascii=False, sort_keys=True)
        existing = self.conn.execute("SELECT id FROM spec_facts WHERE COALESCE(variant_id, -1)=COALESCE(?, -1) AND COALESCE(family_id, -1)=COALESCE(?, -1) AND spec_key=? AND spec_value_json=? AND COALESCE(source, '')=?", (variant_id, family_id, spec_key, value_json, src)).fetchone()
        if existing:
            fid = int(existing["id"]); self.conn.execute("UPDATE spec_facts SET last_seen=?, confidence=MAX(confidence, ?) WHERE id=?", (now, confidence, fid)); return fid
        cur = self.conn.execute("INSERT INTO spec_facts(family_id, variant_id, spec_key, spec_value_json, unit, source, confidence, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (family_id, variant_id, spec_key, value_json, unit, src, confidence, now, now))
        return int(cur.lastrowid)

    def link_listing_variant_candidate(self, *, listing_id: int, variant_id: int, score: float, reason: str = "") -> None:
        self.conn.execute("INSERT OR IGNORE INTO listing_variant_candidates(listing_id, variant_id, family_id, score, reason, created_at) VALUES (?, ?, NULL, ?, ?, ?)", (listing_id, variant_id, score, reason, utc_now_iso()))

    def link_listing_family_candidate(self, *, listing_id: int, family_id: int, score: float, reason: str = "") -> None:
        self.conn.execute("INSERT OR IGNORE INTO listing_variant_candidates(listing_id, variant_id, family_id, score, reason, created_at) VALUES (?, NULL, ?, ?, ?, ?)", (listing_id, family_id, score, reason, utc_now_iso()))




    def enqueue_online_verification(self, listing_id: int, *, query: str = "") -> None:
        now = utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO listing_online_verifications(listing_id, status, query, created_at, updated_at)
            VALUES (?, 'pending', ?, ?, ?)
            ON CONFLICT(listing_id) DO NOTHING
            """,
            (int(listing_id), query, now, now),
        )
        self.conn.commit()

    def enqueue_online_verifications_for_unverified(self, *, limit: int = 1000, include_rejected_clean: bool = True) -> int:
        now = utc_now_iso()
        where_clean = ""
        if not include_rejected_clean:
            where_clean = """
            AND l.id NOT IN (
                SELECT listing_id FROM listing_cleaning_reviews
                WHERE stage='done' AND decision='reject'
            )
            """
        self.conn.execute(
            f"""
            INSERT OR IGNORE INTO listing_online_verifications(listing_id, status, query, created_at, updated_at)
            SELECT l.id, 'pending', '', ?, ?
            FROM listings l
            WHERE l.id NOT IN (SELECT listing_id FROM listing_online_verifications)
            {where_clean}
            LIMIT ?
            """,
            (now, now, int(limit)),
        )
        self.conn.commit()
        return int(self.conn.execute("SELECT changes()").fetchone()[0])

    def pending_online_verifications(self, *, limit: int = 50, prefer_online_research: bool = False, prefer_ai_edge: bool = False) -> list[dict]:
        priority_parts: list[str] = []
        if prefer_ai_edge:
            priority_parts.extend([
                "CASE WHEN ae.status IN ('resolved','uncertain') AND COALESCE(ae.confidence,0) >= 0.72 THEN 0 ELSE 1 END ASC",
                "COALESCE(ae.updated_at, '') DESC",
            ])
        if prefer_online_research:
            priority_parts.extend([
                "CASE WHEN opr.listing_id IS NOT NULL THEN 0 ELSE 1 END ASC",
                "COALESCE(opr.updated_at, '') DESC",
                "COALESCE(cr.updated_at, '') DESC",
            ])
        priority_order = (", ".join(priority_parts) + ", ") if priority_parts else ""
        rows = self.conn.execute(
            f"""
            SELECT
                v.id AS verification_id,
                v.listing_id,
                v.status,
                v.query,
                l.source,
                l.title,
                l.url,
                l.price,
                l.currency,
                l.category,
                l.raw_json,
                cr.decision AS clean_decision,
                cr.confidence AS clean_confidence,
                cr.normalized_title AS clean_title,
                cr.normalized_category AS clean_category,
                cr.reason AS clean_reason,
                mn.title_it AS multilingual_title_it,
                mn.title_en AS multilingual_title_en,
                mn.title_it_hint AS multilingual_title_it_hint,
                mn.title_en_hint AS multilingual_title_en_hint,
                mn.category_canonical AS multilingual_category,
                mn.category_family AS multilingual_category_family,
                mn.product_type_canonical AS multilingual_product_type,
                mn.brand AS multilingual_brand,
                mn.model AS multilingual_model,
                mn.aliases_json AS multilingual_aliases_json,
                mn.confidence AS multilingual_confidence,
                ae.status AS ai_edge_status,
                ae.canonical_title AS ai_edge_canonical_title,
                ae.canonical_brand AS ai_edge_brand,
                ae.canonical_model AS ai_edge_model,
                ae.canonical_category AS ai_edge_category,
                ae.category_family AS ai_edge_category_family,
                ae.product_type AS ai_edge_product_type,
                ae.confidence AS ai_edge_confidence,
                ae.reason AS ai_edge_reason,
                ae.vision_used AS ai_edge_vision_used,
                ae.vision_summary AS ai_edge_vision_summary,
                ae.raw_response_json AS ai_edge_raw_response_json,
                opr.status AS research_status,
                opr.query AS research_query,
                opr.found_sources_json AS research_found_sources_json,
                opr.evidence_snippets_json AS research_evidence_snippets_json,
                opr.diagnostics_json AS research_diagnostics_json,
                opr.canonical_title AS research_canonical_title,
                opr.canonical_brand AS research_brand,
                opr.canonical_model AS research_model,
                opr.canonical_category AS research_category,
                opr.category_family AS research_category_family,
                opr.product_type AS research_product_type,
                opr.aliases_json AS research_aliases_json,
                opr.confidence AS research_confidence,
                opr.reason AS research_reason
            FROM listing_online_verifications v
            JOIN listings l ON l.id = v.listing_id
            LEFT JOIN listing_cleaning_reviews cr ON cr.listing_id = l.id
            LEFT JOIN listing_multilingual_normalizations mn ON mn.listing_id = l.id
            LEFT JOIN listing_online_product_research opr ON opr.listing_id = l.id
            LEFT JOIN listing_ai_edge_reviews ae ON ae.listing_id = l.id
            WHERE v.status='pending'
              AND cr.stage='done'
            ORDER BY {priority_order} v.created_at ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_online_verification_done(
        self,
        *,
        verification_id: int,
        status: str,
        query: str = "",
        confidence: float | None = None,
        reason: str = "",
        evidence: dict | list | None = None,
    ) -> None:
        now = utc_now_iso()
        self.conn.execute(
            """
            UPDATE listing_online_verifications
            SET status=?, query=?, confidence=?, reason=?, evidence_json=?, updated_at=?
            WHERE id=?
            """,
            (
                status,
                query,
                confidence,
                reason,
                json.dumps(evidence or {}, ensure_ascii=False, sort_keys=True),
                now,
                int(verification_id),
            ),
        )
        self.conn.commit()

    def online_verification_summary(self) -> dict:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM listing_online_verifications GROUP BY status ORDER BY status"
        ).fetchall()
        return {str(r["status"]): int(r["n"]) for r in rows}

    @staticmethod
    def _row_float(value, default: float = 0.0) -> float:
        try:
            return float(value if value is not None else default)
        except Exception:
            return default

    @staticmethod
    def _first_nonempty(*values) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    def _trusted_ai_edge_category(self, row) -> tuple[str, str]:
        """Return safe AI-edge category plus a recovery note when guardrails over-shot.

        In M9.7.12 the AI resolver correctly returned technology_desktop_pc for a
        gaming PC, but a substring guardrail saw "table" inside "tablet" in the
        reason text and stored home_furniture_table.  The raw AI JSON is kept, so
        catalog learning can recover from that without rerunning vision.
        """
        stored = _canonical_category_key(row.get("ai_edge_category"))
        raw = _safe_json_object(row.get("ai_edge_raw_response_json"))
        raw_cat = _canonical_category_key(raw.get("canonical_category"))
        reason = str(row.get("ai_edge_reason") or "").lower()
        if raw_cat and raw_cat != stored:
            if (
                "guardrail_ai_technology_to_general_category" in reason
                or "categoria corretta" in reason
                or "category correct" in reason
                or (raw_cat.startswith("technology_") and stored and not stored.startswith("technology_"))
            ):
                return raw_cat, "ai_edge_raw_category_recovered"
        return stored, ""

    def best_researched_title_category(self, row) -> tuple[str, str, dict]:
        ai_edge_confidence = self._row_float(row.get("ai_edge_confidence"), 0.0)
        research_confidence = self._row_float(row.get("research_confidence"), 0.0)
        multilingual_confidence = self._row_float(row.get("multilingual_confidence"), 0.0)

        title = self._first_nonempty(row.get("clean_title"), row.get("title"))
        category = _canonical_category_key(row.get("clean_category")) or _canonical_category_key(row.get("category"))
        source = "clean"
        recovery_note = ""

        if ai_edge_confidence >= _AI_EDGE_CATALOG_MIN_CONFIDENCE and str(row.get("ai_edge_status") or "") == "resolved":
            ai_category, recovery_note = self._trusted_ai_edge_category(row)
            title = self._first_nonempty(row.get("ai_edge_canonical_title"), title)
            if ai_category:
                category = ai_category
            source = "ai_edge_review"
        elif research_confidence >= 0.70:
            title = self._first_nonempty(row.get("research_canonical_title"), title)
            research_category = _canonical_category_key(row.get("research_category"))
            if research_category:
                category = research_category
            source = "online_product_research"
        elif multilingual_confidence >= 0.65:
            title = self._first_nonempty(
                row.get("clean_title"),
                row.get("multilingual_title_en"),
                row.get("multilingual_title_it"),
                row.get("multilingual_title_en_hint"),
                row.get("multilingual_title_it_hint"),
                row.get("title"),
            )
            multilingual_category = _canonical_category_key(row.get("multilingual_category"))
            if multilingual_category:
                category = multilingual_category
            source = "multilingual_normalization"

        evidence = {
            "title_category_source": source,
            "ai_edge_confidence": ai_edge_confidence,
            "ai_edge_status": row.get("ai_edge_status"),
            "ai_edge_category": row.get("ai_edge_category"),
            "ai_edge_safe_category": _canonical_category_key(row.get("ai_edge_category")),
            "ai_edge_product_type": row.get("ai_edge_product_type"),
            "ai_edge_category_recovery": recovery_note,
            "research_confidence": research_confidence,
            "research_category": row.get("research_category"),
            "research_safe_category": _canonical_category_key(row.get("research_category")),
            "research_product_type": row.get("research_product_type"),
            "multilingual_confidence": multilingual_confidence,
            "multilingual_category": row.get("multilingual_category"),
            "multilingual_safe_category": _canonical_category_key(row.get("multilingual_category")),
            "multilingual_product_type": row.get("multilingual_product_type"),
        }
        return title, category, evidence

    @staticmethod
    def _json_list(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            raw = list(value)
        else:
            try:
                raw = json.loads(str(value))
            except Exception:
                raw = []
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for item in raw:
            text = str(item or "").strip()
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                out.append(text)
        return out

    def best_researched_brand_model_aliases(self, row) -> tuple[str, str, list[str], float, str]:
        ai_edge_confidence = self._row_float(row.get("ai_edge_confidence"), 0.0)
        research_confidence = self._row_float(row.get("research_confidence"), 0.0)
        multilingual_confidence = self._row_float(row.get("multilingual_confidence"), 0.0)
        source = "listing"
        confidence = 0.0
        brand = ""
        model = ""
        aliases: list[str] = []

        if ai_edge_confidence >= _AI_EDGE_CATALOG_MIN_CONFIDENCE and str(row.get("ai_edge_status") or "") == "resolved":
            brand = self._first_nonempty(row.get("ai_edge_brand"))
            model = self._first_nonempty(row.get("ai_edge_model"))
            source = "ai_edge_review"
            confidence = ai_edge_confidence
        elif research_confidence >= 0.70:
            brand = self._first_nonempty(row.get("research_brand"))
            model = self._first_nonempty(row.get("research_model"))
            aliases = self._json_list(row.get("research_aliases_json"))
            source = "online_product_research"
            confidence = research_confidence
        elif multilingual_confidence >= 0.65:
            brand = self._first_nonempty(row.get("multilingual_brand"))
            model = self._first_nonempty(row.get("multilingual_model"))
            aliases = self._json_list(row.get("multilingual_aliases_json"))
            source = "multilingual_normalization"
            confidence = multilingual_confidence

        if not aliases:
            aliases = self._json_list(row.get("research_aliases_json")) or self._json_list(row.get("multilingual_aliases_json"))
        return brand, model, aliases, confidence, source

    def promote_verified_listings_to_catalog(self, *, limit: int = 1000, min_confidence: float = 0.55) -> dict:
        from .models import HarvestListing
        from .catalog import upsert_catalog_from_listing
        from .canonicalize import canonicalize_product

        rows = self.conn.execute(
            """
            SELECT
                l.*,
                cr.normalized_title AS clean_title,
                cr.normalized_category AS clean_category,
                mn.title_it AS multilingual_title_it,
                mn.title_en AS multilingual_title_en,
                mn.title_it_hint AS multilingual_title_it_hint,
                mn.title_en_hint AS multilingual_title_en_hint,
                mn.category_canonical AS multilingual_category,
                mn.category_family AS multilingual_category_family,
                mn.product_type_canonical AS multilingual_product_type,
                mn.brand AS multilingual_brand,
                mn.model AS multilingual_model,
                mn.aliases_json AS multilingual_aliases_json,
                mn.confidence AS multilingual_confidence,
                ae.status AS ai_edge_status,
                ae.canonical_title AS ai_edge_canonical_title,
                ae.canonical_brand AS ai_edge_brand,
                ae.canonical_model AS ai_edge_model,
                ae.canonical_category AS ai_edge_category,
                ae.category_family AS ai_edge_category_family,
                ae.product_type AS ai_edge_product_type,
                ae.confidence AS ai_edge_confidence,
                ae.reason AS ai_edge_reason,
                ae.vision_used AS ai_edge_vision_used,
                ae.vision_summary AS ai_edge_vision_summary,
                ae.raw_response_json AS ai_edge_raw_response_json,
                opr.status AS research_status,
                opr.query AS research_query,
                opr.found_sources_json AS research_found_sources_json,
                opr.evidence_snippets_json AS research_evidence_snippets_json,
                opr.diagnostics_json AS research_diagnostics_json,
                opr.canonical_title AS research_canonical_title,
                opr.canonical_brand AS research_brand,
                opr.canonical_model AS research_model,
                opr.canonical_category AS research_category,
                opr.category_family AS research_category_family,
                opr.product_type AS research_product_type,
                opr.aliases_json AS research_aliases_json,
                opr.confidence AS research_confidence,
                opr.reason AS research_reason
            FROM listings l
            JOIN listing_online_verifications v ON v.listing_id = l.id
            LEFT JOIN listing_cleaning_reviews cr ON cr.listing_id = l.id
            LEFT JOIN listing_multilingual_normalizations mn ON mn.listing_id = l.id
            LEFT JOIN listing_online_product_research opr ON opr.listing_id = l.id
            LEFT JOIN listing_ai_edge_reviews ae ON ae.listing_id = l.id
            WHERE v.status IN ('verified', 'verified_conflict')
              AND COALESCE(v.confidence, 0) >= ?
              AND (v.status='verified_conflict' OR COALESCE(cr.decision, 'accept') != 'reject')
            ORDER BY v.updated_at ASC
            LIMIT ?
            """,
            (float(min_confidence), int(limit)),
        ).fetchall()

        promoted = 0
        skipped = 0
        skipped_reasons: dict[str, int] = {}
        learned_categories: dict[str, int] = {}
        learning_sources: dict[str, int] = {}
        examples: list[dict] = []
        for r in rows:
            try:
                r = dict(r)
                raw_json = json.loads(r["raw_json"] or "{}")
                clean_title = (r["clean_title"] or "").strip()
                clean_category = (r["clean_category"] or "").strip()
                promoted_title_seed, promoted_category_seed, promoted_evidence = self.best_researched_title_category(r)
                promoted_brand, promoted_model, promoted_aliases, selected_confidence, identity_source = self.best_researched_brand_model_aliases(r)
                if selected_confidence:
                    promoted_evidence["selected_confidence"] = selected_confidence
                if identity_source and promoted_evidence.get("title_category_source") == "clean":
                    promoted_evidence["identity_source"] = identity_source
                if promoted_evidence.get("title_category_source") == "clean" and selected_confidence < 0.55:
                    skipped += 1
                    skipped_reasons["weak_clean_only_evidence"] = skipped_reasons.get("weak_clean_only_evidence", 0) + 1
                    continue
                safe_seed_category = _canonical_category_key(promoted_category_seed)
                canonical = canonicalize_product(promoted_title_seed or r["title"], safe_seed_category)
                evidence_category = safe_seed_category
                title_only_category = _canonical_category_key(canonical.category)
                clean_category_valid = _canonical_category_key(clean_category)
                title_category_source = str(promoted_evidence.get("title_category_source") or "")
                original_category_hint = self._first_nonempty(r.get("category"), r.get("multilingual_category"), r.get("research_category"))
                real_title_guard_text = " ".join(str(x or "") for x in (r.get("title"), clean_title)).strip()
                evidence_title_guard_text = " ".join(str(x or "") for x in (
                    promoted_title_seed, clean_title, r.get("title"),
                    r.get("research_query"), r.get("ai_edge_vision_summary"), r.get("ai_edge_reason"),
                )).strip()
                # For multilingual/clean-only evidence, use only the real listing text for
                # title-support checks.  Synthetic seeds such as "game console Sony"
                # or "graphics card Apple ID" are category-poisoned output, not evidence.
                title_guard_text = evidence_title_guard_text if title_category_source in {"online_product_research", "ai_edge_review"} else real_title_guard_text
                support_title_guard_text = title_guard_text if title_category_source in {"online_product_research", "ai_edge_review"} else real_title_guard_text
                if _HAZARDOUS_OR_UNSUPPORTED_TITLE_RE.search(support_title_guard_text) or _UNSUPPORTED_DOCUMENT_TITLE_RE.search(support_title_guard_text) or _NON_PRODUCT_TITLE_RE.search(support_title_guard_text):
                    skipped += 1
                    skipped_reasons["unsupported_or_hazardous_title"] = skipped_reasons.get("unsupported_or_hazardous_title", 0) + 1
                    continue
                if _research_category_is_title_unsupported(
                    evidence_category,
                    title_category_source,
                    float(selected_confidence or 0.0),
                    support_title_guard_text,
                ):
                    promoted_evidence["category_guardrail"] = "title_unsupported_research_category_not_promoted"
                    if title_only_category and title_only_category != evidence_category:
                        effective_category = title_only_category
                        evidence_category = title_only_category
                    else:
                        skipped += 1
                        skipped_reasons["title_unsupported_research_category"] = skipped_reasons.get("title_unsupported_research_category", 0) + 1
                        continue
                if title_category_source == "ai_edge_review" and evidence_category and not _category_supported_by_catalog_title(evidence_category, support_title_guard_text):
                    promoted_evidence["category_guardrail"] = "title_unsupported_ai_edge_category_not_promoted"
                    skipped += 1
                    skipped_reasons["title_unsupported_research_category"] = skipped_reasons.get("title_unsupported_research_category", 0) + 1
                    continue
                # Do not let title-only canonicalization override a strong AI/research category.
                # Example: "PC gaming con case..." must stay desktop_pc, not technology_accessory;
                # "Opel Astra H" sold as parts must stay vehicle_car_part when evidence says so.
                effective_category = title_only_category or clean_category_valid
                if _title_category_overrides_evidence(title_only_category, evidence_category, title_guard_text):
                    promoted_evidence["category_guardrail"] = "title_category_overrode_conflicting_evidence"
                    promoted_evidence["overrode_evidence_category"] = evidence_category
                    effective_category = title_only_category
                    # Prevent the later high-confidence evidence branch from restoring the poisoned category.
                    evidence_category = title_only_category
                weak_vehicle_car = _vehicle_category_is_weak(
                    evidence_category,
                    title_category_source,
                    float(selected_confidence or 0.0),
                    support_title_guard_text,
                    original_category_hint,
                )
                if weak_vehicle_car:
                    promoted_evidence["category_guardrail"] = "weak_vehicle_car_not_promoted"
                    if title_only_category and title_only_category != "vehicle_car":
                        effective_category = title_only_category
                    else:
                        skipped += 1
                        skipped_reasons["weak_vehicle_car_evidence"] = skipped_reasons.get("weak_vehicle_car_evidence", 0) + 1
                        continue
                elif evidence_category and selected_confidence >= 0.72:
                    effective_category = evidence_category
                if not effective_category:
                    skipped += 1
                    skipped_reasons["missing_valid_category"] = skipped_reasons.get("missing_valid_category", 0) + 1
                    continue
                if canonical.title:
                    raw_json["promoted_from_title"] = r["title"]
                    raw_json["promoted_normalized_title"] = clean_title
                    raw_json["promoted_canonical_title"] = canonical.title
                    raw_json["promoted_canonical_category"] = effective_category
                    raw_json["promoted_title_only_category"] = title_only_category or canonical.category
                    raw_json["promoted_canonical_warnings"] = canonical.warnings
                    raw_json["promoted_evidence"] = promoted_evidence
                    raw_json["promoted_brand"] = promoted_brand
                    raw_json["promoted_model"] = promoted_model
                    raw_json["promoted_aliases"] = promoted_aliases
                listing = HarvestListing(
                    source=r["source"],
                    title=canonical.title or clean_title or r["title"],
                    url=r["url"],
                    price=r["price"],
                    currency=r["currency"],
                    location=r["location"],
                    seller=r["seller"],
                    condition=r["condition"],
                    image_url=r["image_url"],
                    category=effective_category,
                    query=r["query"],
                    specs=json.loads(r["specs_json"] or "{}"),
                    raw=raw_json,
                )
                resolution = upsert_catalog_from_listing(self, listing, listing_id=int(r["id"]))
                if resolution.family_id is None:
                    skipped += 1
                    continue
                promoted += 1
                cat = str((resolution.analysis or {}).get("category") or listing.category or "unknown")
                src = str((resolution.analysis or {}).get("learning_source") or promoted_evidence.get("title_category_source") or "unknown")
                learned_categories[cat] = learned_categories.get(cat, 0) + 1
                learning_sources[src] = learning_sources.get(src, 0) + 1
                if len(examples) < 12:
                    examples.append({
                        "listing_id": int(r["id"]),
                        "source": r.get("source"),
                        "title": listing.title,
                        "category": cat,
                        "brand": (resolution.analysis or {}).get("brand") or promoted_brand,
                        "model": (resolution.analysis or {}).get("model") or promoted_model,
                        "learning_source": src,
                        "family_id": resolution.family_id,
                        "variant_id": resolution.variant_id,
                    })
            except Exception as exc:
                skipped += 1
                key = f"error:{type(exc).__name__}"
                skipped_reasons[key] = skipped_reasons.get(key, 0) + 1
        self.conn.commit()
        return {
            "selected": len(rows),
            "promoted": promoted,
            "skipped": skipped,
            "skipped_reasons": dict(sorted(skipped_reasons.items())),
            "learned_categories": dict(sorted(learned_categories.items())),
            "learning_sources": dict(sorted(learning_sources.items())),
            "examples": examples,
        }



    def enqueue_cleaning_review(self, listing_id: int, *, reason: str = "post_fetch_cleanup") -> None:
        now = utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO listing_cleaning_reviews(listing_id, stage, reason, created_at, updated_at)
            VALUES (?, 'pending', ?, ?, ?)
            ON CONFLICT(listing_id) DO NOTHING
            """,
            (int(listing_id), reason, now, now),
        )
        self.conn.commit()

    def enqueue_cleaning_reviews_for_unreviewed(self, *, limit: int = 1000) -> int:
        now = utc_now_iso()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO listing_cleaning_reviews(listing_id, stage, reason, created_at, updated_at)
            SELECT id, 'pending', 'post_fetch_cleanup', ?, ?
            FROM listings
            WHERE id NOT IN (SELECT listing_id FROM listing_cleaning_reviews)
            LIMIT ?
            """,
            (now, now, int(limit)),
        )
        self.conn.commit()
        return int(self.conn.execute("SELECT changes()").fetchone()[0])

    def pending_cleaning_reviews(self, *, limit: int = 50, prefer_online_research: bool = False, prefer_ai_edge: bool = False) -> list[dict]:
        priority_parts: list[str] = []
        if prefer_ai_edge:
            priority_parts.extend([
                "CASE WHEN ae.status IN ('resolved','uncertain') AND COALESCE(ae.confidence,0) >= 0.72 THEN 0 ELSE 1 END ASC",
                "COALESCE(ae.updated_at, '') DESC",
            ])
        if prefer_online_research:
            priority_parts.extend([
                "CASE WHEN opr.listing_id IS NOT NULL THEN 0 ELSE 1 END ASC",
                "COALESCE(opr.updated_at, '') DESC",
            ])
        priority_order = (", ".join(priority_parts) + ", ") if priority_parts else ""
        rows = self.conn.execute(
            f"""
            SELECT
                r.id AS review_id,
                r.listing_id,
                r.stage,
                r.reason,
                l.source,
                l.title,
                l.url,
                l.price,
                l.currency,
                l.category,
                l.raw_json,
                mn.title_it AS multilingual_title_it,
                mn.title_en AS multilingual_title_en,
                mn.title_it_hint AS multilingual_title_it_hint,
                mn.title_en_hint AS multilingual_title_en_hint,
                mn.category_canonical AS multilingual_category,
                mn.category_family AS multilingual_category_family,
                mn.product_type_canonical AS multilingual_product_type,
                mn.brand AS multilingual_brand,
                mn.model AS multilingual_model,
                mn.aliases_json AS multilingual_aliases_json,
                mn.confidence AS multilingual_confidence,
                ae.status AS ai_edge_status,
                ae.canonical_title AS ai_edge_canonical_title,
                ae.canonical_brand AS ai_edge_brand,
                ae.canonical_model AS ai_edge_model,
                ae.canonical_category AS ai_edge_category,
                ae.category_family AS ai_edge_category_family,
                ae.product_type AS ai_edge_product_type,
                ae.confidence AS ai_edge_confidence,
                ae.reason AS ai_edge_reason,
                ae.vision_used AS ai_edge_vision_used,
                ae.vision_summary AS ai_edge_vision_summary,
                ae.raw_response_json AS ai_edge_raw_response_json,
                opr.status AS research_status,
                opr.query AS research_query,
                opr.found_sources_json AS research_found_sources_json,
                opr.evidence_snippets_json AS research_evidence_snippets_json,
                opr.diagnostics_json AS research_diagnostics_json,
                opr.canonical_title AS research_canonical_title,
                opr.canonical_brand AS research_brand,
                opr.canonical_model AS research_model,
                opr.canonical_category AS research_category,
                opr.category_family AS research_category_family,
                opr.product_type AS research_product_type,
                opr.aliases_json AS research_aliases_json,
                opr.confidence AS research_confidence,
                opr.reason AS research_reason
            FROM listing_cleaning_reviews r
            JOIN listings l ON l.id = r.listing_id
            LEFT JOIN listing_multilingual_normalizations mn ON mn.listing_id = l.id
            LEFT JOIN listing_online_product_research opr ON opr.listing_id = l.id
            LEFT JOIN listing_ai_edge_reviews ae ON ae.listing_id = l.id
            WHERE r.stage='pending'
            ORDER BY {priority_order} r.created_at ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]

    def reopen_cleaning_reviews_with_online_research(self, *, limit: int = 0) -> int:
        """Move researched listings back to pending so clean can consume fresh evidence.

        This is intentionally narrow: it only targets listings that already have
        cached online product research and whose clean review is currently done.
        Pending rows are left untouched.
        """
        now = utc_now_iso()
        limit_sql = ""
        params: list = [now]
        if limit and int(limit) > 0:
            limit_sql = "LIMIT ?"
            params.append(int(limit))
        self.conn.execute(
            f"""
            UPDATE listing_cleaning_reviews
            SET stage='pending',
                reason='online_research_reclean',
                updated_at=?
            WHERE id IN (
                SELECT cr.id
                FROM listing_cleaning_reviews cr
                JOIN listing_online_product_research opr ON opr.listing_id=cr.listing_id
                WHERE cr.stage='done'
                ORDER BY COALESCE(opr.updated_at, '') DESC, cr.updated_at ASC
                {limit_sql}
            )
            """,
            tuple(params),
        )
        self.conn.commit()
        return int(self.conn.execute("SELECT changes()").fetchone()[0])

    def reopen_cleaning_reviews_with_ai_edge(self, *, limit: int = 0) -> int:
        """Move AI/Vision-reviewed listings back to pending so clean can consume fresh edge evidence.

        Only high-confidence resolved/uncertain AI edge reviews are reopened. Pending
        rows are left untouched.
        """
        now = utc_now_iso()
        limit_sql = ""
        params: list = [now]
        if limit and int(limit) > 0:
            limit_sql = "LIMIT ?"
            params.append(int(limit))
        self.conn.execute(
            f"""
            UPDATE listing_cleaning_reviews
            SET stage='pending',
                reason='ai_edge_reclean',
                updated_at=?
            WHERE id IN (
                SELECT cr.id
                FROM listing_cleaning_reviews cr
                JOIN listing_ai_edge_reviews ae ON ae.listing_id=cr.listing_id
                WHERE cr.stage='done'
                  AND ae.status IN ('resolved','uncertain')
                  AND COALESCE(ae.confidence,0) >= 0.72
                ORDER BY COALESCE(ae.updated_at, '') DESC, cr.updated_at ASC
                {limit_sql}
            )
            """,
            tuple(params),
        )
        self.conn.commit()
        return int(self.conn.execute("SELECT changes()").fetchone()[0])

    def reopen_online_verifications_with_ai_edge(self, *, limit: int = 0) -> int:
        """Re-open existing verifications whose listing received strong AI/Vision evidence."""
        now = utc_now_iso()
        limit_sql = ""
        params: list = [now]
        if limit and int(limit) > 0:
            limit_sql = "LIMIT ?"
            params.append(int(limit))
        self.conn.execute(
            f"""
            UPDATE listing_online_verifications
            SET status='pending',
                reason='ai_edge_reverify',
                updated_at=?
            WHERE id IN (
                SELECT v.id
                FROM listing_online_verifications v
                JOIN listing_ai_edge_reviews ae ON ae.listing_id=v.listing_id
                JOIN listing_cleaning_reviews cr ON cr.listing_id=v.listing_id
                WHERE v.status!='pending'
                  AND cr.stage='done'
                  AND ae.status IN ('resolved','uncertain')
                  AND COALESCE(ae.confidence,0) >= 0.72
                ORDER BY COALESCE(ae.updated_at, '') DESC, v.updated_at ASC
                {limit_sql}
            )
            """,
            tuple(params),
        )
        self.conn.commit()
        return int(self.conn.execute("SELECT changes()").fetchone()[0])

    def mark_cleaning_review_done(
        self,
        *,
        review_id: int,
        stage: str,
        decision: str = "",
        confidence: float | None = None,
        reason: str = "",
        normalized_title: str = "",
        normalized_category: str = "",
        ai_response: str = "",
    ) -> None:
        now = utc_now_iso()
        self.conn.execute(
            """
            UPDATE listing_cleaning_reviews
            SET stage=?, decision=?, confidence=?, reason=?, normalized_title=?,
                normalized_category=?, ai_response=?, updated_at=?
            WHERE id=?
            """,
            (stage, decision, confidence, reason, normalized_title, normalized_category, ai_response, now, int(review_id)),
        )
        self.conn.commit()

    def cleaning_review_summary(self) -> dict:
        rows = self.conn.execute(
            "SELECT stage, COUNT(*) AS n FROM listing_cleaning_reviews GROUP BY stage ORDER BY stage"
        ).fetchall()
        return {str(r["stage"]): int(r["n"]) for r in rows}



    def crawl_task_status(self, *, source: str, task_kind: str, task_key: str) -> str | None:
        row = self.conn.execute(
            "SELECT status FROM crawl_checkpoints WHERE source=? AND task_kind=? AND task_key=?",
            (source, task_kind, task_key),
        ).fetchone()
        return str(row["status"]) if row else None

    def crawl_task_completed(self, *, source: str, task_kind: str, task_key: str) -> bool:
        return self.crawl_task_status(source=source, task_kind=task_kind, task_key=task_key) == "ok"

    def mark_crawl_task_started(
        self,
        *,
        source: str,
        task_kind: str,
        task_key: str,
        category_path: str = "",
        url: str = "",
    ) -> None:
        now = utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO crawl_checkpoints(
                source, task_kind, task_key, category_path, url, status,
                message, saved_count, started_at, finished_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'running', '', 0, ?, NULL, ?)
            ON CONFLICT(source, task_kind, task_key) DO UPDATE SET
                category_path=excluded.category_path,
                url=excluded.url,
                status='running',
                message='',
                started_at=excluded.started_at,
                finished_at=NULL,
                updated_at=excluded.updated_at
            """,
            (source, task_kind, task_key, category_path, url, now, now),
        )
        self.conn.commit()

    def mark_crawl_task_finished(
        self,
        *,
        source: str,
        task_kind: str,
        task_key: str,
        status: str,
        message: str = "",
        saved_count: int = 0,
    ) -> None:
        now = utc_now_iso()
        self.conn.execute(
            """
            UPDATE crawl_checkpoints
            SET status=?, message=?, saved_count=?, finished_at=?, updated_at=?
            WHERE source=? AND task_kind=? AND task_key=?
            """,
            (status, message, int(saved_count or 0), now, now, source, task_kind, task_key),
        )
        self.conn.commit()

    def crawl_checkpoint_summary(self) -> dict:
        """Return checkpoint counts.

        Also includes a search_runs fallback because older/half-running crawlers
        may have written runs before checkpoint writes were introduced.
        """
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM crawl_checkpoints GROUP BY status ORDER BY status"
        ).fetchall()
        checkpoints = {str(r["status"]): int(r["n"]) for r in rows}

        run_rows = self.conn.execute(
            """
            SELECT status, COUNT(*) AS n
            FROM search_runs
            WHERE profile LIKE 'site_category:%'
            GROUP BY status
            ORDER BY status
            """
        ).fetchall()
        search_runs = {str(r["status"]): int(r["n"]) for r in run_rows}

        listing_count = int(self.conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0])
        observation_count = int(self.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0])

        return {
            "checkpoints": checkpoints,
            "search_runs_fallback": search_runs,
            "listings": listing_count,
            "observations": observation_count,
        }

    def recent_crawl_checkpoints(self, *, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT source, task_kind, task_key, category_path, status, saved_count, message, updated_at
            FROM crawl_checkpoints
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        out = [dict(r) for r in rows]
        if out:
            return out

        # Fallback visibility for runs that saved data but did not write the
        # checkpoint table for any reason.
        rows = self.conn.execute(
            """
            SELECT source, profile AS category_path, status, message, started_at, finished_at
            FROM search_runs
            WHERE profile LIKE 'site_category:%'
            ORDER BY COALESCE(finished_at, started_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "source": r["source"],
                "task_kind": "search_run_fallback",
                "task_key": "",
                "category_path": str(r["category_path"]).replace("site_category:", "", 1),
                "status": r["status"],
                "saved_count": 0,
                "message": r["message"],
                "updated_at": r["finished_at"] or r["started_at"],
            }
            for r in rows
        ]


    def catalog_summary(self) -> dict:
        return {
            "families": int(self.conn.execute("SELECT COUNT(*) FROM product_families").fetchone()[0]),
            "variants": int(self.conn.execute("SELECT COUNT(*) FROM product_variants").fetchone()[0]),
            "aliases": int(self.conn.execute("SELECT COUNT(*) FROM product_aliases").fetchone()[0]),
            "identifiers": int(self.conn.execute("SELECT COUNT(*) FROM product_identifiers").fetchone()[0]),
            "spec_facts": int(self.conn.execute("SELECT COUNT(*) FROM spec_facts").fetchone()[0]),
        }

    def query_variants(self, *, category: str | None = None, spec_key: str | None = None, min_numeric_value: float | None = None, limit: int = 50) -> list[dict]:
        where=[]; params=[]
        if category: where.append("pf.category=?"); params.append(category)
        if spec_key: where.append("sf.spec_key=?"); params.append(spec_key)
        sql = "SELECT pf.category, pf.brand, pf.family_name, pv.variant_name, pv.variant_key, sf.spec_key, sf.spec_value_json, sf.unit, sf.confidence FROM product_variants pv JOIN product_families pf ON pf.id = pv.family_id LEFT JOIN spec_facts sf ON sf.variant_id = pv.id"
        if where: sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY pv.last_seen DESC LIMIT ?"; params.append(limit * 3)
        rows = self.conn.execute(sql, params).fetchall(); out=[]; seen=set()
        for row in rows:
            item=dict(row)
            try: value=json.loads(item.get("spec_value_json") or "null")
            except Exception: value=None
            item["spec_value"] = value; item.pop("spec_value_json", None)
            if min_numeric_value is not None and spec_key:
                try:
                    if float(value) < float(min_numeric_value): continue
                except Exception: continue
            key=item["variant_key"]
            if key in seen: continue
            seen.add(key); out.append(item)
            if len(out) >= limit: break
        return out



    def seed_default_categories(self) -> int:
        from .category_schema import seed_category_rows
        now = utc_now_iso()
        count = 0
        for row in seed_category_rows():
            self.conn.execute(
                """
                INSERT INTO category_nodes(category_key, label, parent_key, group_name, keywords_json, profiles_json, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category_key) DO UPDATE SET
                    label=excluded.label,
                    parent_key=excluded.parent_key,
                    group_name=excluded.group_name,
                    keywords_json=excluded.keywords_json,
                    profiles_json=excluded.profiles_json,
                    last_seen=excluded.last_seen
                """,
                (
                    row["category_key"], row["label"], row.get("parent_key") or "", row.get("group_name") or "",
                    json.dumps(row.get("keywords") or [], ensure_ascii=False),
                    json.dumps(row.get("profiles") or [], ensure_ascii=False),
                    now, now,
                ),
            )
            count += 1
        self.conn.commit()
        return count

    def record_product_conflict(
        self,
        *,
        family_id: int | None = None,
        variant_id: int | None = None,
        listing_id: int | None = None,
        conflict_key: str,
        claimed_value=None,
        canonical_value=None,
        source: str = "",
        status: str = "open",
    ) -> int:
        now = utc_now_iso()
        cur = self.conn.execute(
            """
            INSERT INTO product_conflicts(
                family_id, variant_id, listing_id, conflict_key, claimed_value_json,
                canonical_value_json, source, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                family_id,
                variant_id,
                listing_id,
                conflict_key,
                json.dumps(claimed_value, ensure_ascii=False, sort_keys=True),
                json.dumps(canonical_value, ensure_ascii=False, sort_keys=True),
                source,
                status,
                now,
            ),
        )
        return int(cur.lastrowid)

    def conflict_summary(self) -> dict:
        rows = self.conn.execute(
            "SELECT conflict_key, status, COUNT(*) AS n FROM product_conflicts GROUP BY conflict_key, status ORDER BY n DESC"
        ).fetchall()
        return {f"{r['conflict_key']}:{r['status']}": int(r['n']) for r in rows}


    def upsert_many(self, listings: Iterable[HarvestListing], *, run_id: int | None = None) -> int:
        count = 0
        for listing in listings:
            self.upsert_listing(listing, run_id=run_id)
            count += 1
        return count

    def count_listings(self, *, source: str | None = None) -> int:
        if source:
            return int(self.conn.execute("SELECT COUNT(*) FROM listings WHERE source=?", (source,)).fetchone()[0])
        return int(self.conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0])

    def recent_listings(self, *, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT source, title, price, currency, url, query, specs_json, last_seen, seen_count
            FROM listings
            ORDER BY last_seen DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["specs"] = json.loads(item.pop("specs_json") or "{}")
            except Exception:
                item["specs"] = {}
            out.append(item)
        return out
