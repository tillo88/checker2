from __future__ import annotations

import re
from dataclasses import dataclass

_CURRENCY_PREFIX_PRICE_RE = re.compile(r"(?:€|eur|euro|chf|£|gbp|\$|usd)\s*[0-9][0-9.,]*", re.I)
_CURRENCY_SUFFIX_PRICE_RE = re.compile(r"[0-9][0-9.,]*\s*(?:€|eur|euro|chf|£|gbp|\$|usd)", re.I)
_RATING_BEFORE_PRICE_RE = re.compile(r"\b[0-5][,.][0-9]\s*(?=(?:€|eur|euro|chf|£|gbp|\$|usd)\s*\d|\d{2,}[,.]?\d*\s*(?:€|eur|euro|chf|£|gbp|\$|usd))", re.I)
_CONDITION_RE = re.compile(r"\((?:new|nuovo|used|usato|refurbished|ricondizionato|eccellente|ottimo|buono)\)", re.I)
_MARKETING_PREFIX_RE = re.compile(r"^(?:bestseller|just a few left|pochi rimasti|pochi pezzi rimasti|solo pochi rimasti|deal|offerta|new|nuovo|sale)\s+", re.I)
_MARKETING_SUFFIX_RE = re.compile(r"\b(?:in vendita|nuovo|nuova|usato|usata|ricondizionato|ricondizionata|refurbished|offerta|deal)\b", re.I)
_TRAILING_JUNK_RE = re.compile(r"(?:\s+[0-5][,.]\s*|\s+\d{1,2}\.\s*|\s+\d{1,2},\s*)$")


def parse_euro_number(value: str) -> float | None:
    s = re.sub(r"\s+", "", str(value or ""))
    if not s:
        return None
    if "." in s and "," in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        if re.search(r",\d{1,2}$", s):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s:
        if re.search(r"\.\d{3}$", s):
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def canonicalize_title(title: str) -> str:
    t = re.sub(r"\s+", " ", title or "").strip()
    prev = None
    while prev != t:
        prev = t
        t = _MARKETING_PREFIX_RE.sub("", t).strip()
    t = _RATING_BEFORE_PRICE_RE.sub(" ", t)
    t = _CURRENCY_PREFIX_PRICE_RE.sub(" ", t)
    t = _CURRENCY_SUFFIX_PRICE_RE.sub(" ", t)
    t = _CONDITION_RE.sub(" ", t)
    t = _MARKETING_SUFFIX_RE.sub(" ", t)
    t = re.sub(r"\b(?:rating|recensione|recensioni|incl\.?|con boost)\b", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" -|·")
    prev = None
    while prev != t:
        prev = t
        t = _TRAILING_JUNK_RE.sub("", t).strip(" -|·")
    return t


_CATEGORY_RULES: tuple[tuple[str, str], ...] = (
    (r"\b(laptop\s*scherm|laptopscherm|laptop\s+screen|replacement\s+screen|display\s+panel)\b", "technology_accessory"),
    (r"\b(ipad|tablet|galaxy\s+tab|tab\s+[a-z0-9]|nokia\s+t20|lenovo\s+tab|surface\s+pro)\b", "technology_tablet"),
    (r"\b(macbook|thinkpad|tp\s*t\d{3,4}|t\d{3,4}s?|latitude|elitebook|zbook|notebook|laptop|portatile|computer\s+portatile|hp\s+250r)\b", "technology_laptop"),
    (r"\b(apple\s+watch|smartwatch|watch\s+series|watch\s+ultra|galaxy\s+watch)\b", "technology_smartwatch"),
    (r"\b(iphone|galaxy\s+s\d|galaxy\s+z|pixel\s+\d|smartphone|telefono|cellulare)\b", "technology_smartphone"),
    (r"\b(rtx|gtx|quadro|radeon|rx\s?\d{3,4}|arc\s?a\d{3,4}|gpu|scheda\s+video|vram|gddr)\b", "technology_gpu"),
    (r"\b(airpods?|earpods?|beats|bose|jabra|plantronics|quietcomfort|wh-\d|wf-\d|headphones?|headset|hoofdtelefoons?|koptelefoon|kopfh[oö]rer|cuffie|auricolari|sony\s+w[fh]|savi\s+\d|biz\s+\d)\b", "technology_audio_headphones"),
    (r"\b(amplificatore|amplificador|amplifier|verstärker|verstarker|pedalera|hifi amplifier|hb-40r)\b", "technology_audio_amplifier"),
    (r"\b(giradischi|turntable|platenspeler|plattenspieler|tocadiscos|record player)\b", "technology_audio_turntable"),
    (r"\b(desktop pc|pc desktop|mini pc|tower pc|computer fisso)\b", "technology_desktop_pc"),
    (r"\b(monitor|bildschirm|beeldscherm|wqhd|qhd|uhd)\b", "technology_monitor"),
    (r"\b(stampante|printer|drucker|imprimante|impresora|drukarka)\b", "technology_printer"),
    (r"\b(console|playstation|ps[2345]|xbox|nintendo\s+switch|steam deck|spelcomputer)\b", "technology_console"),
    (r"\b(mouse|magic\s+mouse)\b", "technology_mouse"),
    (r"\b(keyboard|tastiera|toetsenbord|tastatur|clavier|teclado)\b", "technology_keyboard"),
    (r"\b(charger|caricatore|cavo|usb-c|cover|case|custodia|pellicola|screen protector|dock|docking|hub)\b", "technology_accessory"),
    (r"\b(fotolijst|fotolijsten|photo frame|picture frame|cornice|cornici|bilderrahmen|cadre photo|marco de fotos|fotografie in cornici)\b", "home_decor_photo_frame"),
    (r"\b(quadro|quadri|poster|wall art|decorazione parete|wandbild|kunstdruck|tableau|cuadro|obraz|plakat)\b", "home_decor_wall_art"),
    (r"\b(tapis\s+roulant|treadmill|l[oø]?\s*beb[aå]?nd|loebebaand|running\s+machine|speed\s+rope|sjippetov|jump\s+rope|skipping\s+rope)\b", "sports_fitness_equipment"),
    (r"\b(biljardbord|billiard table|pool table|billardtisch|tavolo da biliardo)\b", "sports_billiards"),
    (r"\b(tavolo|dining table|coffee table|tisch|tafel|bord|pöytä|poyta|neuvottelupöytä|neuvottelupoyta|palettentisch|balkonmöbel|gartenmöbel|gartenmoebel)\b", "home_furniture_table"),
    (r"\b(sedia|sedie|chair|chairs|stuhl|stühle|stuhle|sessel|hocker|sgabello|tuoli|istuinkoroke)\b", "home_furniture_chair"),
    (r"\b(vorratsdose|aufbewahrungsdose|storage container|food container|contenitore|barattolo|ikea vorratsdose)\b", "home_storage_container"),
    (r"\b(skoletaske|school bag|schoolbag|zaino scuola|schulranzen|schultasche|schooltas|plecak szkolny|koulureppu)\b", "school_bag"),
    (r"\b(wobbler|abu garcia tormentor|fishing lure|esca artificiale|fiskedrag|viehe)\b", "sports_fishing_lure"),
    (r"\b(casa\s+de\s+muñecas|casa\s+de\s+munecas|doll\s*house|dollhouse|puppenhaus)\b", "toys_dollhouse"),
    (r"\b(lego|lego figur|lego figure|minifigure|minifigura|playmobil)\b", "toys_lego"),
    (r"\b(skjutmått|skjutmatt|caliper|calibro|schieblehre|messschieber|suwmiarka|työntömitta|tyontomitta)\b", "tools_measuring_caliper"),
    (r"\b(modulfräser|modulfraeser|fräser|fraeser|milling cutter|gear cutter|cutting tool)\b", "tools_cutting_tool"),
    (r"\b(baul de moto|baúl de moto|baule moto|bauletto moto|top case|topcase|motorradkoffer)\b", "vehicle_motorcycle_accessory"),
    (r"\b(części samochodowe|czesci samochodowe|kompresor klimatyzacji|klimakompressor|felgenschloss|ricambio auto|car part|auto part)\b", "vehicle_car_part"),
    (r"\b(automobile|voiture|coche|samochod|samochód|gebrauchtwagen|used car|auto usata|auto nuova|opel\s+astra|honda\s+ntv|mercedes|bmw|audi|fiat|ford|peugeot|renault)\b", "vehicle_car"),
    (r"\b(saszetka|nerka|marsupio|fanny\s+pack|waist\s+bag|belt\s+bag|handbag|borsa|pochette)\b", "fashion_bag"),
    (r"\b(polo|shirt|t-shirt|maglia|camicia|chaqueta|giacca|morgenmantel|bata|vaelluskeng[aä]t|scarpe|shoes|abbigliamento|vestiti|clothing|kleidung|kleding|ropa|ralph lauren|h&m|c\.p\. company|cp company|ragno)\b", "fashion_clothing"),
    (r"\b(libro|vendo libro|book|buch|książka|ksiazka|livre)\b", "books_media_book"),
    (r"\b(rotationslaser|laser level|livella laser|nivela laser)\b", "technology_laser_level"),
    (r"\b(fotelik\s+samochodowy|seggiolino\s+auto|turvakaukalo|car\s+seat|child\s+seat|britax\s+r[oö]mer|britax\s+romer)\b", "baby_child_car_seat"),
    (r"\b(czynnik\s+ch[lł]odniczy|r134a|r404a|r407c|r410a|refrigerant|gas\s+refrigerante)\b", "unknown"),
    (r"\b(bateria acustica|batería acústica|batteria acustica|drums|custom drums)\b", "music_drums"),
)

_FALLBACK_MAP = {
    "accessori": "technology_accessory",
    "accessories": "technology_accessory",
    "accessorio": "technology_accessory",
    "portatili": "technology_laptop",
    "laptop": "technology_laptop",
    "notebook": "technology_laptop",
    "smartphone": "technology_smartphone",
    "cellulari": "technology_smartphone",
    "telefoni": "technology_smartphone",
    "tablet": "technology_tablet",
    "smartwatch": "technology_smartwatch",
    "audio": "technology_audio",
    "cuffie": "technology_audio_headphones",
    "hoofdtelefoons": "technology_audio_headphones",
    "marsupio": "fashion_bag",
    "nerka": "fashion_bag",
    "hardware": "technology_hardware",
    "hardware gaming": "technology_gpu",
    "accessori elettronici": "technology_accessory",
    "computer portatile": "technology_laptop",
    "fotografie | fotolijsten": "home_decor_photo_frame",
    "møbler og indretning": "home_furniture_table",
    "möbler och inredning": "home_furniture_table",
    "koti ja sisustus": "home_furniture_table",
}


def canonical_category_from_title(title: str, fallback: str = "") -> str:
    tl = (title or "").lower()
    fb = (fallback or "").strip().lower()
    hay = f"{tl} {fb}"
    for pattern, category in _CATEGORY_RULES:
        if re.search(pattern, hay, re.I):
            return category
    return _FALLBACK_MAP.get(fb, fallback or "unknown")


@dataclass
class CanonicalProduct:
    title: str
    category: str
    warnings: list[str]


def canonicalize_product(title: str, category: str = "") -> CanonicalProduct:
    clean = canonicalize_title(title)
    warnings: list[str] = []
    if clean != (title or "").strip():
        warnings.append("title_canonicalized")
    if len(clean) < 4:
        warnings.append("short_canonical_title")
    cat = canonical_category_from_title(clean, category)
    if cat != (category or ""):
        warnings.append("category_canonicalized")
    return CanonicalProduct(clean, cat, warnings)
