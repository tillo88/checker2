from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import re
import unicodedata
from typing import Iterable


def strip_accents(value: str) -> str:
    value = str(value or "")
    return "".join(
        c for c in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(c)
    )


def norm_text(value: str) -> str:
    value = strip_accents(str(value or "")).lower()
    value = re.sub(r"[^a-z0-9+._\- ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def unique_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        item = str(item or "").strip()
        if not item:
            continue
        key = norm_text(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


LANGUAGE_HINTS: dict[str, list[str]] = {
    "it": [
        "spedizione", "venditore", "ritiro", "usato", "nuovo", "ottime condizioni",
        "lavatrice", "scheda video", "portatile", "telefono", "stampante",
    ],
    "en": [
        "shipping", "seller", "pickup", "used", "new", "excellent condition",
        "washing machine", "graphics card", "laptop", "headphones", "printer",
    ],
    "de": [
        "versand", "abholung", "verkaufer", "verkaeufer", "gebraucht", "neu",
        "waschmaschine", "grafikkarte", "kopfhörer", "kopfhorer", "lautsprecher",
    ],
    "fr": [
        "livraison", "retrait", "vendeur", "occasion", "neuf", "lave linge",
        "lave-linge", "carte graphique", "ordinateur portable", "casque audio",
    ],
    "es": [
        "envio", "envío", "entrega", "recogida", "vendedor", "usado", "nuevo",
        "lavadora", "tarjeta grafica", "tarjeta gráfica", "portatil", "portátil",
    ],
    "nl": [
        "verzending", "ophalen", "verkoper", "gebruikt", "nieuw", "wasmachine",
        "videokaart", "koptelefoon", "luidspreker", "harde schijven",
    ],
    "pl": [
        "wysylka", "wysyłka", "sprzedawca", "uzywany", "używany", "nowy",
        "pralka", "karta graficzna", "laptop", "drukarka",
    ],
    "da": [
        "forsendelse", "afhentning", "sælger", "saelger", "brugt", "ny",
        "vaskemaskine", "grafikkort", "hovedtelefoner", "printer",
    ],
    "fi": [
        "toimitus", "nouto", "myyja", "myyjä", "kaytetty", "käytetty", "uusi",
        "pesukone", "naytonohjain", "näytönohjain", "kuulokkeet",
    ],
    "sv": [
        "frakt", "upphamtning", "upphämtning", "saljare", "säljare", "begagnad",
        "tvattmaskin", "tvättmaskin", "grafikkort", "horlurar", "hörlurar",
    ],
}


SOURCE_LANGUAGE_DEFAULTS: dict[str, str] = {
    "2dehands": "nl",
    "marktplaats": "nl",
    "blocket": "sv",
    "dba": "da",
    "kleinanzeigen": "de",
    "rebuy": "de",
    "refurbed": "it",
    "olx_pl": "pl",
    "tori": "fi",
    "wallapop": "es",
    "willhaben": "de",
    "swappie": "it",
    "vinted": "it",
}


def source_language_default(source: str) -> str:
    return SOURCE_LANGUAGE_DEFAULTS.get(str(source or "").strip().lower(), "unknown")


def apply_source_language_hint(source: str, lang: str, confidence: float, scores: dict[str, int]) -> tuple[str, float, dict[str, int]]:
    """Use source locale as a fallback/weak override for sparse text.

    Many listing titles are short and language detection from keywords alone is weak.
    If the detector is unknown or low-confidence, prefer the marketplace locale
    while preserving the raw scores for inspection.
    """
    fallback = source_language_default(source)
    if not fallback or fallback == "unknown":
        return lang, confidence, scores
    score_total = sum(scores.values()) if scores else 0
    if lang == "unknown" or confidence < 0.6 or score_total <= 2:
        out_scores = dict(scores or {})
        out_scores[f"source_hint:{fallback}"] = out_scores.get(f"source_hint:{fallback}", 0) + 1
        return fallback, max(float(confidence or 0.0), 0.55), out_scores
    return lang, confidence, scores


@dataclass(frozen=True)
class TaxonomyEntry:
    canonical: str
    product_type: str
    it_label: str
    en_label: str
    aliases: tuple[str, ...]
    category_family: str = "general"


TAXONOMY: tuple[TaxonomyEntry, ...] = (
    TaxonomyEntry(
        "technology_gpu", "gpu", "scheda video", "graphics card",
        ("scheda video", "gpu", "graphics card", "grafikkarte", "carte graphique",
         "tarjeta grafica", "tarjeta gráfica", "videokaart", "karta graficzna",
         "grafikkort", "naytonohjain", "näytönohjain", "rtx", "geforce", "radeon", "quadro"),
        "technology",
    ),
    TaxonomyEntry(
        "technology_ram", "ram", "memoria RAM", "memory RAM",
        ("ram", "memoria ram", "arbeitsspeicher", "speicher", "memory", "ddr4", "ddr5",
         "so-dimm", "sodimm", "dimm"),
        "technology",
    ),
    TaxonomyEntry(
        "technology_server_parts", "server_part", "componente server", "server part",
        ("server", "serverlama", "proliant", "poweredge", "dl360", "dl380", "r730", "r740",
         "drive cage", "backplane", "raid controller", "hba", "pdu", "network switch",
         "switch ethernet", "netwerkkabel", "network cable"),
        "technology",
    ),
    TaxonomyEntry(
        "technology_storage_ssd", "ssd", "SSD", "SSD",
        ("ssd", "nvme", "m.2", "m2", "solid state", "solid-state", "harde schijven",
         "festplatte", "disque ssd", "dysk ssd", "hard disk", "hard drive"),
        "technology",
    ),
    TaxonomyEntry(
        "technology_laptop", "laptop", "portatile", "laptop",
        ("laptop", "notebook", "portatile", "ordinateur portable", "portatil", "portátil",
         "lenovo thinkpad", "thinkpad", "macbook", "zbook", "surface laptop"),
        "technology",
    ),
    TaxonomyEntry(
        "technology_desktop_pc", "desktop_pc", "PC desktop", "desktop PC",
        ("desktop pc", "pc desktop", "mini pc", "computer fisso", "desktop-pc", "tower pc",
         "computer de bureau", "pc de sobremesa"),
        "technology",
    ),
    TaxonomyEntry(
        "technology_smartphone", "smartphone", "smartphone", "smartphone",
        ("smartphone", "telefono", "cellulare", "iphone", "samsung galaxy", "handy",
         "mobile phone", "téléphone", "telephone", "teléfono", "telefon", "gsm"),
        "technology",
    ),
    TaxonomyEntry(
        "technology_tablet", "tablet", "tablet", "tablet",
        ("tablet", "ipad", "galaxy tab", "surface pro", "tablette", "tablet-pc"),
        "technology",
    ),
    TaxonomyEntry(
        "technology_smartwatch", "smartwatch", "smartwatch", "smartwatch",
        ("smartwatch", "apple watch", "galaxy watch", "orologio smart", "watch"),
        "technology",
    ),
    TaxonomyEntry(
        "technology_monitor", "monitor", "monitor", "monitor",
        ("monitor", "schermo", "display", "bildschirm", "ecran", "écran", "pantalla",
         "beeldscherm", "wqhd", "qhd", "uhd"),
        "technology",
    ),
    TaxonomyEntry(
        "technology_printer", "printer", "stampante", "printer",
        ("stampante", "printer", "drucker", "imprimante", "impresora", "drukarka",
         "copier", "scanner", "multifunzione"),
        "technology",
    ),
    TaxonomyEntry(
        "technology_laser_level", "laser_level", "livella laser", "laser level",
        ("rotationslaser", "laser level", "nivela laser", "livella laser", "niveau laser", "laserafstandsmeter", "laser distance"),
        "technology_tools",
    ),
    TaxonomyEntry(
        "technology_audio_amplifier", "amplifier", "amplificatore", "amplifier",
        ("amplificatore", "amplificador", "amplifier", "verstarker", "verstärker", "receiver", "pedalera", "amp", "hifi amplifier"),
        "technology_audio",
    ),
    TaxonomyEntry(
        "music_drums", "drums", "batteria acustica", "drums",
        ("bateria acustica", "batería acústica", "batteria acustica", "drums", "custom drums", "tamburi"),
        "music",
    ),
    TaxonomyEntry(
        "technology_audio_headphones", "headphones", "cuffie", "headphones",
        ("cuffie", "auricolari", "headphones", "headset", "hoofdtelefoon", "hoofdtelefoons",
         "kopfhörer", "kopfhorer", "casque audio", "écouteurs", "ecouteurs", "auriculares", "koptelefoon",
         "hovedtelefoner", "kuulokkeet", "hörlurar", "horlurar", "airpods"),
        "technology_audio",
    ),
    TaxonomyEntry(
        "technology_audio_turntable", "turntable", "giradischi", "turntable",
        ("giradischi", "turntable", "record player", "platenspeler", "plattenspieler",
         "tocadiscos", "tourne disque", "tourne-disque", "vinyl player", "lettore vinile",
         "auto-stop", "autostop phono", "phono retro"),
        "technology_audio",
    ),
    TaxonomyEntry(
        "technology_audio_speakers", "speakers", "casse audio", "speakers",
        ("speaker", "speakers", "casse", "altoparlanti", "lautsprecher", "enceintes",
         "luidspreker", "luidsprekers", "højttaler", "hojttaler", "kaiutin",
         "högtalare", "hogtalare", "soundbar"),
        "technology_audio",
    ),
    TaxonomyEntry(
        "technology_camera", "camera", "fotocamera", "camera",
        ("fotocamera", "camera", "kamera", "appareil photo", "camara", "cámara",
         "fujifilm", "canon", "nikon", "sony alpha", "lens", "obiettivo"),
        "technology",
    ),
    TaxonomyEntry(
        "technology_console", "console", "console", "game console",
        ("console", "playstation", "ps2", "ps3", "ps4", "ps5", "xbox", "nintendo",
         "switch", "steam deck", "spelcomputer"),
        "technology_gaming",
    ),
    TaxonomyEntry(
        "technology_accessory", "accessory", "accessorio elettronico", "tech accessory",
        ("cavo", "usb-c", "usb c", "charger", "caricatore", "cavo di ricarica", "charging cable",
         "cover", "custodia", "case", "screen protector", "pellicola", "hub", "dock", "docking station"),
        "technology",
    ),
    TaxonomyEntry(
        "technology_keyboard", "keyboard", "tastiera", "keyboard",
        ("tastiera", "keyboard", "toetsenbord", "tastatur", "clavier", "teclado",
         "gaming keyboard"),
        "technology",
    ),
    TaxonomyEntry(
        "technology_mouse", "mouse", "mouse", "mouse",
        ("mouse", "maus", "souris", "raton", "ratón", "muis", "magic mouse"),
        "technology",
    ),
    TaxonomyEntry(
        "appliance_washing_machine", "washing_machine", "lavatrice", "washing machine",
        ("lavatrice", "washing machine", "waschmaschine", "lave linge", "lave-linge",
         "lavadora", "wasmachine", "pralka", "vaskemaskine", "pesukone",
         "tvattmaskin", "tvättmaskin"),
        "home_appliance",
    ),
    TaxonomyEntry(
        "appliance_dryer", "dryer", "asciugatrice", "dryer",
        ("asciugatrice", "dryer", "trockner", "seche linge", "sèche-linge",
         "secadora", "droger", "suszarka", "torretumbler", "kuivausrumpu", "torktumlare"),
        "home_appliance",
    ),
    TaxonomyEntry(
        "appliance_fridge", "fridge", "frigorifero", "fridge",
        ("frigorifero", "fridge", "refrigerator", "kühlschrank", "kuhlschrank",
         "réfrigérateur", "refrigerateur", "frigorifico", "lodówka", "koelkast", "køleskab"),
        "home_appliance",
    ),
    TaxonomyEntry(
        "home_decor_photo_frame", "photo_frame", "cornice fotografica", "photo frame",
        ("fotolijst", "fotolijsten", "fotografie fotolijsten", "photo frame", "picture frame",
         "cornice", "cornici", "cornice fotografica", "foto incorniciata", "fotografie in cornici",
         "bilderrahmen", "cadre photo", "marco de fotos", "marco fotos", "ramka", "ramka na zdjecia",
         "ramka na zdjęcia", "fotoramme", "kuvakehys", "fotoram"),
        "home_decor",
    ),
    TaxonomyEntry(
        "home_decor_wall_art", "wall_art", "decorazione parete", "wall art",
        ("quadro", "quadri", "poster", "stampa", "print", "wall art", "decorazione parete",
         "wandbild", "kunstdruck", "tableau", "cuadro", "obraz", "plakat", "taulu"),
        "home_decor",
    ),
    TaxonomyEntry(
        "home_furniture_table", "table", "tavolo", "table",
        ("tavolo", "dining table", "coffee table", "tisch", "tafel", "bord", "pöytä", "poyta", "neuvottelupöytä",
         "neuvottelupoyta", "palettentisch", "balkonmöbel", "balkonmobel", "gartenmoebel", "gartenmöbel"),
        "home_furniture",
    ),
    TaxonomyEntry(
        "home_furniture_chair", "chair", "sedia", "chair",
        ("sedia", "sedie", "chair", "chairs", "stuhl", "stühle", "stuhle", "sessel", "chaise", "silla",
         "krzeslo", "krzesło", "tuoli", "stol", "hocker", "sgabello", "istuinkoroke"),
        "home_furniture",
    ),
    TaxonomyEntry(
        "home_storage_container", "storage_container", "contenitore", "storage container",
        ("contenitore", "barattolo", "vasetto", "vorratsdose", "aufbewahrungsdose", "storage container",
         "food container", "voorraaddoos", "opbevaringsboks", "säilytysrasia", "sailytysrasia",
         "förvaringsburk", "forvaringsburk", "ikea vorratsdose"),
        "home_storage",
    ),
    TaxonomyEntry(
        "school_bag", "school_bag", "zaino scuola", "school bag",
        ("skoletaske", "school bag", "schoolbag", "zaino scuola", "cartella scuola", "schulranzen",
         "schultasche", "schooltas", "tornister", "plecak szkolny", "koulureppu", "skolväska", "skolvaska"),
        "bags",
    ),
    TaxonomyEntry(
        "sports_fitness_equipment", "fitness_equipment", "attrezzo fitness", "fitness equipment",
        ("tapis roulant", "treadmill", "løbebånd", "lobeband", "loebebaand", "running machine",
         "speed rope", "sjippetov", "jump rope", "skipping rope", "elastik"),
        "sports",
    ),
    TaxonomyEntry(
        "sports_billiards", "billiard_table", "tavolo da biliardo", "billiard table",
        ("biljardbord", "billiard", "billiards", "billiard table", "pool table", "billardtisch",
         "tavolo da biliardo", "billard", "billardbord"),
        "sports",
    ),
    TaxonomyEntry(
        "sports_fishing_lure", "fishing_lure", "esca da pesca", "fishing lure",
        ("wobbler", "abu garcia tormentor", "fishing lure", "lure", "esca", "esca artificiale",
         "pesca", "köder", "koder", "fiskedrag", "viehe"),
        "sports",
    ),
    TaxonomyEntry(
        "toys_dollhouse", "dollhouse", "casa delle bambole", "dollhouse",
        ("casa de muñecas", "casa de munecas", "dollhouse", "doll house", "puppenhaus"),
        "toys",
    ),
    TaxonomyEntry(
        "toys_lego", "lego_figure", "LEGO", "LEGO",
        ("lego", "lego figur", "lego figure", "minifigure", "minifigura", "minifig", "playmobil"),
        "toys",
    ),
    TaxonomyEntry(
        "baby_child_car_seat", "child_car_seat", "seggiolino auto bambini", "child car seat",
        ("seggiolino auto", "fotelik samochodowy", "turvakaukalo", "car seat", "child seat",
         "britax römer", "britax romer"),
        "baby_child",
    ),
    TaxonomyEntry(
        "vehicle_car_part", "car_part", "ricambio auto", "car part",
        ("car part", "auto part", "ricambio auto", "pezzo auto", "teile", "autoteile", "ersatzteil",
         "części samochodowe", "czesci samochodowe", "kompresor klimatyzacji", "klimakompressor",
         "felgenschloss", "bumper", "paraurti", "range rover evoque", "otomoto"),
        "vehicles",
    ),
    TaxonomyEntry(
        "vehicle_motorcycle_accessory", "motorcycle_accessory", "accessorio moto", "motorcycle accessory",
        ("baul de moto", "baúl de moto", "baule moto", "bauletto moto", "top case", "topcase",
         "motorcycle top box", "motorradkoffer", "moto", "motorcycle accessory"),
        "vehicles",
    ),
    TaxonomyEntry(
        "tools_measuring_caliper", "caliper", "calibro", "caliper",
        ("skjutmått", "skjutmatt", "calibro", "caliper", "vernier caliper", "schieblehre",
         "messschieber", "suwmiarka", "skydekaliber", "työntömitta", "tyontomitta"),
        "tools",
    ),
    TaxonomyEntry(
        "tools_cutting_tool", "cutting_tool", "fresa", "cutting tool",
        ("modulfräser", "modulfraeser", "fräser", "fraeser", "fresa", "frese", "milling cutter",
         "gear cutter", "cutting tool", "satz 8st"),
        "tools",
    ),
    TaxonomyEntry(
        "books_media_book", "book", "libro", "book",
        ("libro", "vendo libro", "book", "buch", "książka", "ksiazka", "livre", "libro usado"),
        "books_media",
    ),
    TaxonomyEntry(
        "vehicle_car", "car", "auto", "car",
        ("automobile", "voiture", "coche", "samochod", "samochód",
         "motoryzacja", "auto usata", "auto nuova", "used car", "gebrauchtwagen"),
        "vehicles",
    ),
    TaxonomyEntry(
        "fashion_bag", "bag", "borsa/marsupio", "bag",
        ("borsa", "marsupio", "saszetka", "nerka", "fanny pack", "waist bag", "belt bag",
         "handbag", "pochette", "bauchtasche"),
        "fashion",
    ),
    TaxonomyEntry(
        "fashion_clothing", "clothing", "abbigliamento", "clothing",
        ("abbigliamento", "vestiti", "fashion", "clothing", "kleidung", "kleding",
         "vêtements", "vetements", "ropa", "odzież", "odziez", "klær", "klaer",
         "vaatteet", "kläder", "klader", "polo", "shirt", "t-shirt", "maglia", "camicia",
         "chaqueta", "giacca", "morgenmantel", "bata", "scarpe", "shoes", "vaelluskengät", "vaelluskengat",
         "ragno", "ralph lauren", "h&m", "c.p. company", "cp company"),
        "fashion",
    ),
)


ALIAS_TO_ENTRY: dict[str, TaxonomyEntry] = {}
for entry in TAXONOMY:
    for alias in entry.aliases:
        ALIAS_TO_ENTRY[norm_text(alias)] = entry


BRAND_HINTS = (
    "apple", "samsung", "sony", "dell", "lenovo", "hp", "hpe", "asus", "acer",
    "msi", "nvidia", "amd", "intel", "logitech", "bose", "teufel", "yamaha",
    "canon", "nikon", "fujifilm", "ricoh", "transcend", "kingston", "crucial",
    "seagate", "western digital", "wd", "microsoft", "surface", "lg", "philips",
    "ikea", "harley benton", "boss", "ce johansson", "ralph lauren", "lego", "opel", "abu garcia",
)


def detect_language(text: str) -> tuple[str, float, dict[str, int]]:
    hay = " " + norm_text(text) + " "
    scores: dict[str, int] = {}
    for lang, hints in LANGUAGE_HINTS.items():
        score = 0
        for hint in hints:
            h = norm_text(hint)
            if h and f" {h} " in hay:
                score += 2
            elif h and h in hay:
                score += 1
        if score:
            scores[lang] = score

    # Small character/hint boosts.
    raw = str(text or "").lower()
    if any(c in raw for c in "äöüß"):
        scores["de"] = scores.get("de", 0) + 1
    if any(c in raw for c in "åøæ"):
        scores["da"] = scores.get("da", 0) + 1
    if any(c in raw for c in "ąęłńóśźż"):
        scores["pl"] = scores.get("pl", 0) + 1
    if any(c in raw for c in "åäö") and not any(c in raw for c in "ßü"):
        scores["sv"] = scores.get("sv", 0) + 1

    if not scores:
        return "unknown", 0.0, {}
    lang, best = max(scores.items(), key=lambda kv: kv[1])
    total = sum(scores.values())
    confidence = min(0.99, max(0.35, best / max(total, 1)))
    return lang, round(confidence, 3), scores


def detect_taxonomy(text: str) -> tuple[TaxonomyEntry | None, list[str], dict[str, int]]:
    hay = " " + norm_text(text) + " "
    scores: dict[str, int] = {}
    matched_aliases: list[str] = []

    for alias_norm, entry in ALIAS_TO_ENTRY.items():
        if not alias_norm:
            continue
        # Avoid generic/short false positives such as nl "bil" inside unrelated text
        # or generic words that are often used in product descriptions.
        if len(alias_norm) <= 3 and alias_norm not in {"gpu", "ssd", "ram"}:
            continue
        score = 0
        if f" {alias_norm} " in hay:
            score = 4
        elif len(alias_norm) >= 5 and alias_norm in hay:
            score = 2
        elif alias_norm in {"gpu", "ssd", "ram"} and re.search(rf"\b{re.escape(alias_norm)}\b", hay):
            score = 3

        if score:
            scores[entry.canonical] = scores.get(entry.canonical, 0) + score
            matched_aliases.append(alias_norm)

    if not scores:
        return None, [], {}
    canonical = max(scores.items(), key=lambda kv: kv[1])[0]
    entry = next(e for e in TAXONOMY if e.canonical == canonical)
    return entry, unique_keep_order(matched_aliases), scores



_GENERIC_SPEC_ALIASES = {
    "ram", "memory", "memoria ram", "memory ram", "speicher", "display",
    "monitor", "schermo", "camera", "fotocamera", "ssd", "nvme", "gpu",
    "mouse", "tastiera", "keyboard",
}


def _category_prior_entry(category: str) -> TaxonomyEntry | None:
    """Return an entry when the stored category is already a canonical/product key.

    This prevents generic spec words from snippets (RAM/display/camera) from
    overriding an explicit marketplace/detail category such as technology_tablet.
    """
    cat = norm_text(category).replace("-", "_").replace(" ", "_")
    if not cat or cat in {"unknown", "none", "null"}:
        return None
    for entry in TAXONOMY:
        if cat == entry.canonical or cat == entry.product_type:
            return entry
    return None


def _aliases_for_entry(entry: TaxonomyEntry | None, aliases: list[str]) -> list[str]:
    if not entry:
        return []
    allowed = {norm_text(entry.it_label), norm_text(entry.en_label)}
    allowed.update(norm_text(a) for a in entry.aliases)
    return unique_keep_order([a for a in aliases if norm_text(a) in allowed])



_CATEGORY_SUPPORT_PATTERNS: dict[str, str] = {
    "technology_smartphone": r"\b(iphone|smartphone|cellulare|telefono|pixel\s+\d|google\s+pixel|galaxy\s+(?:s|z|a)\d|xiaomi|redmi|oneplus|mobile\s+phone)\b",
    "technology_ram": r"\b(ram|ddr[345]|so-?dimm|sodimm|dimm|arbeitsspeicher|memoria\s+ram)\b",
    "technology_laptop": r"\b(laptop|notebook|thinkpad|latitude|elitebook|zbook|macbook|laptopscherm|laptop\s+screen)\b",
    "technology_monitor": r"\b(monitor|beeldscherm|bildschirm|schermo|display|wqhd|qhd|uhd)\b",
    "technology_audio_amplifier": r"\b(amplificatore|amplificador|amplifier|verst[aä]rker|receiver|pedalera|hb-40r|hifi\s+amplifier)\b",
    "technology_audio_headphones": r"\b(cuffie|auricolari|headphones?|headset|hoofdtelefoons?|koptelefoon|kopfh[oö]rer|airpods|earbuds?)\b",
    "technology_accessory": r"\b(usb-?c|charger|caricatore|charging\s+cable|cavo|cover|custodia|screen\s+protector|hub|dock|laptopscherm|laptop\s+screen)\b",
    "technology_desktop_pc": r"\b(desktop\s+pc|pc\s+desktop|mini\s+pc|tower\s+pc|computer\s+fisso|gaming\s+pc)\b",
    "technology_console": r"\b(console|playstation|ps[2345]|xbox|nintendo\s+switch|steam\s+deck|spelcomputer)\b",
    "technology_tablet": r"\b(ipad|tablet|galaxy\s+tab|surface\s+pro|tab\s+s\d+)\b",
    "technology_gpu": r"\b(rtx|gtx|radeon|quadro|gpu|scheda\s+video|graphics\s+card|vram|gddr)\b",
}


def _entry_by_key(key: str) -> TaxonomyEntry | None:
    for entry in TAXONOMY:
        if entry.canonical == key:
            return entry
    return None


def _category_supported_by_title(category: str, title_context: str) -> bool:
    category = str(category or "")
    if not category or category == "unknown":
        return False
    pattern = _CATEGORY_SUPPORT_PATTERNS.get(category)
    if not pattern:
        return True
    return bool(re.search(pattern, norm_text(title_context), re.I))


def _special_title_entry(title_context: str) -> TaxonomyEntry | None:
    blob = norm_text(title_context)
    ordered: tuple[tuple[str, str], ...] = (
        (r"\b(czynnik\s+ch\s*odniczy|czynnik\s+chlodniczy|czynnik\s+chłodniczy|r134a|r404a|r407c|r410a|refrigerant)\b", "unknown"),
        (r"\b(cuffie|auricolari|headphones?|headset|hoofdtelefoons?|koptelefoon|kopfh[oö]rer|airpods|earbuds?)\b", "technology_audio_headphones"),
        (r"\b(tapis\s+roulant|treadmill|l[oø]?\s*beb[aå]?nd|loebebaand|running\s+machine|speed\s+rope|sjippetov|jump\s+rope|skipping\s+rope|elastik)\b", "sports_fitness_equipment"),
        (r"\b(saszetka|nerka|marsupio|fanny\s+pack|waist\s+bag|belt\s+bag|handbag|borsa|pochette)\b", "fashion_bag"),
        (r"\b(laptop\s*scherm|laptopscherm|laptop\s+screen|replacement\s+screen|display\s+panel)\b", "technology_accessory"),
        (r"\b(fotelik\s+samochodowy|seggiolino\s+auto|turvakaukalo|car\s+seat|child\s+seat|britax\s+r[oö]mer|britax\s+romer)\b", "baby_child_car_seat"),
        (r"\b(sessel|stuhl|stühle|stuhle|sedia|chair|chairs|istuinkoroke)\b", "home_furniture_chair"),
        (r"\b(casa\s+de\s+muñecas|casa\s+de\s+munecas|doll\s*house|dollhouse|puppenhaus)\b", "toys_dollhouse"),
    )
    for pattern, key in ordered:
        if re.search(pattern, blob, re.I):
            return None if key == "unknown" else _entry_by_key(key)
    return None

def _taxonomy_from_title_first(
    *,
    title_context: str,
    combined: str,
    category: str,
) -> tuple[TaxonomyEntry | None, list[str], dict[str, int]]:
    """Prefer product identity from title/category over generic snippet/spec words.

    Online snippets often contain generic specs like RAM, display, SSD, camera,
    keyboard, mouse. Those are useful aliases only when the title/category points
    to that product class; otherwise they can flip an iPad into RAM or a caliper
    into a monitor. This resolver keeps title/category as the primary signal and
    uses description/snippets only as fallback.
    """
    category_entry = _category_prior_entry(category)
    title_entry, title_aliases, title_scores = detect_taxonomy(title_context)
    combined_entry, combined_aliases, combined_scores = detect_taxonomy(combined)
    special_entry = _special_title_entry(title_context)

    if special_entry:
        aliases = _aliases_for_entry(special_entry, title_aliases + combined_aliases)
        return special_entry, aliases, title_scores or {special_entry.canonical: 6}

    if title_entry:
        return title_entry, _aliases_for_entry(title_entry, title_aliases + combined_aliases), title_scores or {title_entry.canonical: 4}

    if category_entry and _category_supported_by_title(category_entry.canonical, title_context):
        aliases = _aliases_for_entry(category_entry, combined_aliases)
        scores = dict(combined_scores or {})
        scores[category_entry.canonical] = max(scores.get(category_entry.canonical, 0), 4)
        return category_entry, aliases, scores

    if not combined_entry:
        return None, [], {}

    # Description-only generic specs are weak evidence, especially for unknown
    # categories. Example: search snippets for a caliper page mentioning display
    # should not make the listing a monitor.
    aliases_for_combined = _aliases_for_entry(combined_entry, combined_aliases)
    if aliases_for_combined and all(norm_text(a) in _GENERIC_SPEC_ALIASES for a in aliases_for_combined):
        return None, [], {}

    return combined_entry, aliases_for_combined, combined_scores

def detect_brand(text: str) -> str:
    hay = " " + norm_text(text) + " "
    # Product-family inference kept title-only by callers. Do not infer brands
    # from generic web snippets, otherwise a MINI PC result can become HP just
    # because an unrelated HP snippet was returned.
    if re.search(r"\b(iphone|ipad|macbook|imac|apple watch|airpods|magic mouse)\b", hay):
        return "Apple"
    for brand in BRAND_HINTS:
        b = norm_text(brand)
        if f" {b} " in hay or hay.startswith(b + " "):
            return brand.upper() if brand in {"hp", "hpe", "lg", "wd"} else brand.title()
    return ""


BAD_MODEL_PREFIXES = {
    "voor", "vanaf", "van", "dan", "met", "zonder", "nieuw", "oude",
    "old", "new", "from", "with", "without", "for", "website",
    "sinds", "seit", "noin", "circa", "ca", "med", "circa", "vanaf",
    "per", "prijs", "price", "geschikt", "ongeveer",
}

BAD_MODEL_EXACT_RE = re.compile(
    r"^(?:voor|vanaf|van|dan|met|without|with|for|from|sinds|seit|noin|med|ca|circa)\s+\d{1,4}\b",
    re.I,
)


def looks_like_model(value: str, *, source_text: str = "", allow_not_in_title: bool = False) -> bool:
    value = str(value or "").strip()
    if not value:
        return False
    norm = norm_text(value)
    if not norm:
        return False
    first = norm.split(" ", 1)[0]
    if first in BAD_MODEL_PREFIXES or BAD_MODEL_EXACT_RE.search(value):
        return False
    if re.fullmatch(r"\d{1,4}", norm):
        return False
    if len(norm) < 2:
        return False

    source_norm = norm_text(source_text)
    if source_norm and norm not in source_norm and not allow_not_in_title:
        # Do not trust models invented from detail boilerplate/descriptions.
        return False

    # Good model patterns: alphanumeric product tokens, known product names, or
    # short brand family strings containing a digit/revision.
    good_patterns = [
        r"\brtx\s?\d{3,4}(?:\s?ti|\s?super)?\b",
        r"\brx\s?\d{3,4}(?:\s?xt)?\b",
        r"\biphone\s?(?:se\s?)?\d{1,2}\b",
        r"\bmacbook\s?(?:air|pro)?(?:\s?\d{4})?(?:\s?m\d)?\b",
        r"\bthinkpad\s?[a-z]?\d{3,4}[a-z]?\b",
        r"\b[a-z]{1,6}[-\s]?\d{2,5}[a-z0-9\-]*\b",
        r"\b\d{2,5}[a-z]{1,4}\b",
        r"\b[a-z]+\s(?:air|pro|se|max|mini)\s?\d{0,4}\b",
        r"\b[a-z]+\s\d{3,4}gb\b",
    ]
    return any(re.search(p, norm, flags=re.I) for p in good_patterns)


def extract_model_hint(text: str) -> str:
    raw = str(text or "")
    patterns = [
        r"\bRTX\s?\d{3,4}(?:\s?Ti| SUPER)?\b",
        r"\bRX\s?\d{3,4}(?:\s?XT)?\b",
        r"\biPhone\s?(?:SE\s?)?\d{1,2}(?:\s?(?:Pro|Max|Plus|mini|Air))*\b",
        r"\bMacBook\s?(?:Air|Pro)?\s?\d{4}?\s?(?:M\d)?\b",
        r"\bThinkPad\s?[A-Z]?\d{3,4}[A-Z]?\b",
        r"\bDL\d{3,4}\b",
        r"\bU\d{4}[A-Za-z]*\b",
        r"\bP\d{4}[A-Za-z]*\b",
        r"\b[A-Z]{2,6}[-\s]?\d{2,5}[A-Z0-9\-]*\b",
    ]
    for pat in patterns:
        for m in re.finditer(pat, raw, flags=re.I):
            candidate = re.sub(r"\s+", " ", m.group(0)).strip()
            if re.match(r"^[aA][-]?\d", candidate):
                continue
            if looks_like_model(candidate, source_text=raw):
                return candidate
    return ""


def _entry_by_canonical(canonical: str) -> TaxonomyEntry | None:
    for entry in TAXONOMY:
        if entry.canonical == canonical:
            return entry
    return None


def _refresh_derived_fields(out: dict) -> dict:
    entry = _entry_by_canonical(str(out.get("category_canonical") or "unknown"))
    brand = str(out.get("brand") or "").strip()
    model = str(out.get("model") or "").strip()
    base_title = str(out.get("resolved_title") or out.get("title_original") or "")
    category = str(out.get("category_original") or "")
    if entry:
        out["category_family"] = entry.category_family
        if not out.get("product_type_canonical") or out.get("product_type_canonical") == "unknown":
            out["product_type_canonical"] = entry.product_type
        # Keep AI aliases but prepend taxonomy aliases, then dedupe.
        out["aliases"] = unique_keep_order([entry.it_label, entry.en_label, *entry.aliases, *(out.get("aliases") or [])])
        out["title_it_hint"] = " ".join(x for x in [entry.it_label, brand, model] if x).strip()
        out["title_en_hint"] = " ".join(x for x in [entry.en_label, brand, model] if x).strip()
    else:
        out["category_canonical"] = "unknown"
        out["category_family"] = "unknown"
        if out.get("product_type_canonical") not in {"amplifier", "drums", "laser_level"}:
            out["product_type_canonical"] = "unknown"
        out["aliases"] = []
        out["title_it_hint"] = ""
        out["title_en_hint"] = ""

    out["title_search_normalized"] = norm_text(" ".join([
        base_title,
        category,
        str(out.get("category_canonical") or "unknown"),
        str(out.get("product_type_canonical") or "unknown"),
        brand,
        model,
        " ".join((out.get("aliases") or [])[:12]),
    ]))
    return out


def postprocess_normalization(norm: dict) -> dict:
    """Final deterministic safety pass after AI merge.

    Keeps broad AI output useful while removing known hallucination/false-positive
    patterns from European marketplace text.
    """
    out = dict(norm)
    title_context = " ".join([
        str(out.get("title_original") or ""),
        str(out.get("resolved_title") or ""),
        str(out.get("category_original") or ""),
    ])
    title_blob = norm_text(title_context)

    # Normalize AI-specific product types into stable canonicals.
    product_type = norm_text(str(out.get("product_type_canonical") or ""))
    if re.search(r"\b(czynnik\s+ch\s*odniczy|czynnik\s+chlodniczy|czynnik\s+chłodniczy|r134a|r404a|r407c|r410a|refrigerant)\b", title_blob):
        out["category_canonical"] = "unknown"
        out["category_family"] = "unknown"
        out["product_type_canonical"] = "unknown"
        out["confidence"] = min(float(out.get("confidence") or 0.25), 0.35)
    elif re.search(r"\b(cuffie|auricolari|headphones?|headset|hoofdtelefoons?|koptelefoon|kopfh[oö]rer|airpods|earbuds?)\b", title_blob):
        out["category_canonical"] = "technology_audio_headphones"
        out["category_family"] = "technology_audio"
        out["product_type_canonical"] = "headphones"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.84)
    elif re.search(r"\b(tapis\s+roulant|treadmill|l[oø]?\s*beb[aå]?nd|loebebaand|running\s+machine|speed\s+rope|sjippetov|jump\s+rope|skipping\s+rope|elastik)\b", title_blob):
        out["category_canonical"] = "sports_fitness_equipment"
        out["category_family"] = "sports"
        out["product_type_canonical"] = "fitness_equipment"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)
    elif re.search(r"\b(saszetka|nerka|marsupio|fanny\s+pack|waist\s+bag|belt\s+bag|handbag|borsa|pochette)\b", title_blob):
        out["category_canonical"] = "fashion_bag"
        out["category_family"] = "fashion"
        out["product_type_canonical"] = "bag"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)
    elif re.search(r"\b(laptop\s*scherm|laptopscherm|laptop\s+screen|replacement\s+screen|display\s+panel)\b", title_blob):
        out["category_canonical"] = "technology_accessory"
        out["category_family"] = "technology"
        out["product_type_canonical"] = "display_part"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)
    elif re.search(r"\b(fotelik\s+samochodowy|seggiolino\s+auto|turvakaukalo|car\s+seat|child\s+seat|britax\s+r[oö]mer|britax\s+romer)\b", title_blob):
        out["category_canonical"] = "baby_child_car_seat"
        out["category_family"] = "baby_child"
        out["product_type_canonical"] = "child_car_seat"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)
    elif product_type in {"technology_audio_amplifier", "audio_amplifier", "amplifier", "amp"} or re.search(r"\b(amplificatore|amplificador|amplifier|verstarker|verstärker|pedalera)\b", title_blob):
        out["category_canonical"] = "technology_audio_amplifier"
        out["category_family"] = "technology_audio"
        out["product_type_canonical"] = "amplifier"
    elif product_type in {"technology_audio_drums", "audio_drums", "drums"} or re.search(r"\b(bateria acustica|batería acústica|custom drums|drums)\b", title_blob):
        out["category_canonical"] = "music_drums"
        out["category_family"] = "music"
        out["product_type_canonical"] = "drums"
    elif product_type in {"laser_level", "technology_laser_level"} or re.search(r"\b(rotationslaser|laser level|livella laser)\b", title_blob):
        out["category_canonical"] = "technology_laser_level"
        out["category_family"] = "technology_tools"
        out["product_type_canonical"] = "laser_level"

    elif re.search(r"\b(cavo di ricarica|usb-c|usb c|charging cable|charger|caricatore|cover|custodia|screen protector|hub|dock)\b", title_blob):
        out["category_canonical"] = "technology_accessory"
        out["category_family"] = "technology"
        out["product_type_canonical"] = "accessory"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)

    # General marketplace taxonomy. These categories are intentionally non-tech:
    # profile selection (tech/all) should decide later whether to promote them.
    if re.search(r"\b(fotolijst|fotolijsten|photo frame|picture frame|cornice|cornici|bilderrahmen|cadre photo|marco de fotos|fotografie in cornici)\b", title_blob):
        out["category_canonical"] = "home_decor_photo_frame"
        out["category_family"] = "home_decor"
        out["product_type_canonical"] = "photo_frame"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)
    elif re.search(r"\b(quadro|quadri|poster|wall art|decorazione parete|wandbild|kunstdruck|tableau|cuadro|obraz|plakat)\b", title_blob):
        out["category_canonical"] = "home_decor_wall_art"
        out["category_family"] = "home_decor"
        out["product_type_canonical"] = "wall_art"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.78)
    elif re.search(r"\b(skoletaske|school bag|schoolbag|zaino scuola|schulranzen|schultasche|schooltas|plecak szkolny|koulureppu)\b", title_blob):
        out["category_canonical"] = "school_bag"
        out["category_family"] = "bags"
        out["product_type_canonical"] = "school_bag"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)
    elif re.search(r"\b(sessel|stuhl|stühle|stuhle|sedia|chair|chairs|istuinkoroke)\b", title_blob):
        out["category_canonical"] = "home_furniture_chair"
        out["category_family"] = "home_furniture"
        out["product_type_canonical"] = "chair"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.78)
    elif re.search(r"\b(casa\s+de\s+muñecas|casa\s+de\s+munecas|doll\s*house|dollhouse|puppenhaus)\b", title_blob):
        out["category_canonical"] = "toys_dollhouse"
        out["category_family"] = "toys"
        out["product_type_canonical"] = "dollhouse"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)
    elif re.search(r"\b(vorratsdose|aufbewahrungsdose|storage container|food container|contenitore|barattolo|ikea vorratsdose)\b", title_blob):
        out["category_canonical"] = "home_storage_container"
        out["category_family"] = "home_storage"
        out["product_type_canonical"] = "storage_container"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)
    elif re.search(r"\b(biljardbord|billiard table|pool table|billardtisch|tavolo da biliardo)\b", title_blob):
        out["category_canonical"] = "sports_billiards"
        out["category_family"] = "sports"
        out["product_type_canonical"] = "billiard_table"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)
    elif re.search(r"\b(wobbler|abu garcia tormentor|fishing lure|esca artificiale|fiskedrag|viehe)\b", title_blob):
        out["category_canonical"] = "sports_fishing_lure"
        out["category_family"] = "sports"
        out["product_type_canonical"] = "fishing_lure"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)
    elif re.search(r"\b(lego|lego figur|lego figure|minifigure|minifigura|playmobil)\b", title_blob):
        out["category_canonical"] = "toys_lego"
        out["category_family"] = "toys"
        out["product_type_canonical"] = "lego_figure"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)
    elif re.search(r"\b(skjutmått|skjutmatt|caliper|calibro|schieblehre|messschieber|suwmiarka|työntömitta|tyontomitta)\b", title_blob):
        out["category_canonical"] = "tools_measuring_caliper"
        out["category_family"] = "tools"
        out["product_type_canonical"] = "caliper"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)
    elif re.search(r"\b(modulfräser|modulfraeser|fräser|fraeser|milling cutter|gear cutter|cutting tool)\b", title_blob):
        out["category_canonical"] = "tools_cutting_tool"
        out["category_family"] = "tools"
        out["product_type_canonical"] = "cutting_tool"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)
    elif re.search(r"\b(baul de moto|baúl de moto|baule moto|bauletto moto|top case|topcase|motorradkoffer)\b", title_blob):
        out["category_canonical"] = "vehicle_motorcycle_accessory"
        out["category_family"] = "vehicles"
        out["product_type_canonical"] = "motorcycle_accessory"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)
    elif re.search(r"\b(części samochodowe|czesci samochodowe|kompresor klimatyzacji|klimakompressor|felgenschloss|ricambio auto|car part|auto part)\b", title_blob):
        out["category_canonical"] = "vehicle_car_part"
        out["category_family"] = "vehicles"
        out["product_type_canonical"] = "car_part"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.78)

    # Never classify audio auto-stop / auto-stop turntables as cars. Also keep
    # car seats/parts out of generic vehicle_car unless confidence is high and
    # this database actually wants vehicles later.
    if out.get("category_canonical") == "vehicle_car" and not re.search(
        r"\b(automobile|voiture|coche|samochod|samochód|motoryzacja|gebrauchtwagen|used car|auto usata|auto nuova)\b",
        title_blob,
    ):
        out["category_canonical"] = "unknown"
        out["category_family"] = "unknown"
        out["product_type_canonical"] = "unknown"
        out["confidence"] = min(float(out.get("confidence") or 0.25), 0.35)

    # Car seats and car parts are not whole cars, but they are still valid marketplace items.
    if re.search(r"\b(fotelik samochodowy|car seat|child seat|kompresor klimatyzacji|czesci samochodowe|części samochodowe|felgenschloss)\b", title_blob):
        if out.get("category_canonical") == "vehicle_car":
            out["category_canonical"] = "vehicle_car_part"
            out["category_family"] = "vehicles"
            out["product_type_canonical"] = "car_part"
            out["confidence"] = max(float(out.get("confidence") or 0.25), 0.78)

    # HPE ProLiant / drive-cage / backplane are server parts even when NVMe is mentioned.
    if re.search(r"\b(proliant|dl360|dl380|drive cage|backplane|server)\b", title_blob):
        out["category_canonical"] = "technology_server_parts"
        out["category_family"] = "technology"
        out["product_type_canonical"] = "server_part"
        out["confidence"] = max(float(out.get("confidence") or 0.0), 0.82)

    # Validate AI/deterministic model. Prefer models present in title/resolved title.
    model = str(out.get("model") or "").strip()
    if model and not looks_like_model(model, source_text=title_context, allow_not_in_title=False):
        out["model"] = ""

    if out.get("aliases"):
        out["aliases"] = unique_keep_order(out.get("aliases") or [])

    return _refresh_derived_fields(out)


def build_aliases(entry: TaxonomyEntry | None, matched_aliases: list[str]) -> list[str]:
    if not entry:
        return unique_keep_order(matched_aliases)
    return unique_keep_order([entry.it_label, entry.en_label, *entry.aliases, *matched_aliases])


def normalize_multilingual_listing(
    *,
    title: str,
    category: str = "",
    description: str = "",
    resolved_title: str = "",
    source: str = "",
) -> dict:
    original_title = str(title or "").strip()
    detail_title = str(resolved_title or "").strip()
    category = str(category or "").strip()
    description = str(description or "").strip()

    # Prefer resolved/detail title for taxonomy signals, but keep original.
    combined = " ".join([detail_title, original_title, category, description])
    title_context = " ".join([detail_title, original_title, category])
    lang, lang_conf, lang_scores = detect_language(combined)
    lang, lang_conf, lang_scores = apply_source_language_hint(source, lang, lang_conf, lang_scores)
    entry, matched_aliases, taxonomy_scores = _taxonomy_from_title_first(
        title_context=title_context,
        combined=combined,
        category=category,
    )
    # Brand must come from listing title/category context, not arbitrary web snippets.
    brand = detect_brand(title_context)
    # Model extraction intentionally avoids description boilerplate by default.
    model = extract_model_hint(title_context)
    aliases = build_aliases(entry, matched_aliases)

    canonical = entry.canonical if entry else "unknown"
    product_type = entry.product_type if entry else "unknown"
    category_family = entry.category_family if entry else "unknown"

    confidence = 0.25
    if entry:
        confidence += 0.45
    if matched_aliases:
        confidence += min(0.2, 0.04 * len(matched_aliases))
    if brand:
        confidence += 0.05
    if model:
        confidence += 0.05
    confidence = round(min(0.98, confidence), 3)

    title_search = norm_text(" ".join([
        detail_title or original_title,
        category,
        canonical,
        product_type,
        brand,
        model,
        " ".join(aliases[:12]),
    ]))

    title_it_hint = ""
    title_en_hint = ""
    if entry:
        title_it_hint = " ".join(x for x in [entry.it_label, brand, model] if x).strip()
        title_en_hint = " ".join(x for x in [entry.en_label, brand, model] if x).strip()

    result = {
        "method": "deterministic",
        "source": source,
        "language_detected": lang,
        "language_confidence": lang_conf,
        "language_scores": lang_scores,
        "title_original": original_title,
        "resolved_title": detail_title,
        "title_it_hint": title_it_hint,
        "title_en_hint": title_en_hint,
        "title_search_normalized": title_search,
        "category_original": category,
        "category_canonical": canonical,
        "category_family": category_family,
        "product_type_canonical": product_type,
        "brand": brand,
        "model": model,
        "aliases": aliases,
        "matched_aliases": matched_aliases,
        "taxonomy_scores": taxonomy_scores,
        "confidence": confidence,
    }

    return postprocess_normalization(result)

def merge_ai_normalization(det: dict, ai: dict | None) -> dict:
    if not ai:
        return det
    out = dict(det)
    safe_keys = {
        "language_detected", "title_it", "title_en", "category_canonical",
        "category_family", "product_type_canonical", "brand", "model", "aliases",
        "confidence",
    }
    for key in safe_keys:
        if key in ai and ai[key] not in (None, "", []):
            out[key] = ai[key]
    out["method"] = "ai+deterministic"
    out["ai_raw"] = ai
    if "aliases" in out:
        out["aliases"] = unique_keep_order(out.get("aliases") or [])
    try:
        out["confidence"] = round(float(out.get("confidence", det.get("confidence", 0.5))), 3)
    except Exception:
        out["confidence"] = det.get("confidence", 0.5)
    return postprocess_normalization(out)


def extract_json_object(text: str) -> dict:
    text = str(text or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def normalization_compact_for_raw_json(norm: dict) -> dict:
    keys = [
        "method", "language_detected", "title_it", "title_en", "title_it_hint",
        "title_en_hint", "title_search_normalized", "category_canonical",
        "category_family", "product_type_canonical", "brand", "model",
        "aliases", "confidence",
    ]
    return {k: norm.get(k) for k in keys if k in norm}
