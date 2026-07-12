from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryNode:
    key: str
    label: str
    parent: str = ""
    group: str = ""
    keywords: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ()


DEFAULT_CATEGORY_NODES: tuple[CategoryNode, ...] = (
    CategoryNode("technology", "Tecnologia", group="root", keywords=("elettronica", "tech", "computer")),
    CategoryNode("technology_gpu", "Schede video / GPU", parent="technology", group="pc_components", profiles=("gpu_vram_catalog", "tech"), keywords=("scheda video", "gpu", "rtx", "radeon", "vram", "gddr")),
    CategoryNode("technology_ram", "RAM desktop/notebook", parent="technology", group="pc_components", profiles=("ram_ddr4_catalog", "tech"), keywords=("ram", "memoria", "ddr4", "ddr5", "sodimm", "udimm")),
    CategoryNode("technology_monitor", "Monitor", parent="technology", group="display", profiles=("monitor_catalog", "tech"), keywords=("monitor", "display", "oled", "ips", "hz", "ultrawide")),
    CategoryNode("technology_storage", "SSD / HDD", parent="technology", group="pc_components", profiles=("tech",), keywords=("ssd", "nvme", "m.2", "hdd", "hard disk")),
    CategoryNode("technology_cpu", "CPU / processori", parent="technology", group="pc_components", profiles=("tech",), keywords=("cpu", "processore", "ryzen", "intel core", "xeon")),
    CategoryNode("technology_tablet", "Tablet", parent="technology", group="mobile", profiles=("refurbished_electronics", "tech"), keywords=("ipad", "tablet", "galaxy tab", "surface pro")),
    CategoryNode("technology_smartphone", "Smartphone", parent="technology", group="mobile", profiles=("refurbished_electronics", "tech"), keywords=("iphone", "smartphone", "telefono", "pixel", "galaxy")),
    CategoryNode("technology_smartwatch", "Smartwatch", parent="technology", group="wearables", profiles=("refurbished_electronics", "tech"), keywords=("apple watch", "smartwatch", "galaxy watch")),
    CategoryNode("technology_laptop", "Laptop / workstation", parent="technology", group="computers", profiles=("refurbished_electronics", "tech"), keywords=("laptop", "notebook", "thinkpad", "macbook", "zbook")),
    CategoryNode("technology_desktop_pc", "PC desktop / mini PC", parent="technology", group="computers", profiles=("tech",), keywords=("desktop pc", "mini pc", "computer fisso", "tower pc")),
    CategoryNode("technology_console", "Console gaming", parent="technology", group="gaming", profiles=("refurbished_electronics", "tech"), keywords=("playstation", "xbox", "switch", "steam deck", "console")),
    CategoryNode("technology_audio", "Audio", parent="technology", group="audio", profiles=("tech",), keywords=("audio", "hifi", "speaker")),
    CategoryNode("technology_audio_headphones", "Cuffie / auricolari", parent="technology_audio", group="audio", profiles=("tech",), keywords=("cuffie", "headphones", "airpods", "auricolari")),
    CategoryNode("technology_audio_speakers", "Casse / speaker audio", parent="technology_audio", group="audio", profiles=("tech",), keywords=("casse audio", "speaker", "speakers", "luidspreker", "soundbar")),
    CategoryNode("technology_audio_amplifier", "Amplificatori audio", parent="technology_audio", group="audio", profiles=("tech",), keywords=("amplificatore", "amplifier", "amplificador", "receiver")),
    CategoryNode("technology_audio_turntable", "Giradischi", parent="technology_audio", group="audio", profiles=("tech",), keywords=("giradischi", "turntable", "plattenspieler")),
    CategoryNode("technology_accessory", "Accessori tecnologia", parent="technology", group="accessories", profiles=("tech",), keywords=("cavo", "usb-c", "charger", "cover", "dock", "hub")),
    CategoryNode("technology_laser_level", "Livelle laser", parent="technology", group="tools", profiles=("tech", "tools"), keywords=("livella laser", "laser level", "rotationslaser")),
    CategoryNode("tools", "Utensili / strumenti", group="root", keywords=("utensili", "tools", "strumenti")),
    CategoryNode("tools_battery", "Utensili a batteria", parent="tools", group="tools", profiles=("tools_battery_catalog", "tools"), keywords=("trapano", "avvitatore", "makita 18v", "bosch 18v", "dewalt")),
    CategoryNode("tools_measuring_caliper", "Calibri / strumenti di misura", parent="tools", group="tools", profiles=("tools", "all"), keywords=("calibro", "caliper", "skjutmått", "messschieber", "suwmiarka")),
    CategoryNode("tools_cutting_tool", "Frese / utensili da taglio", parent="tools", group="tools", profiles=("tools", "all"), keywords=("fresa", "modulfräser", "milling cutter", "cutting tool")),
    CategoryNode("home", "Casa", group="root", keywords=("casa", "home", "arredamento")),
    CategoryNode("home_decor", "Decorazione casa", parent="home", group="home_decor", profiles=("all",), keywords=("decorazione", "wall art", "cornice", "foto")),
    CategoryNode("home_decor_photo_frame", "Cornici fotografiche", parent="home_decor", group="home_decor", profiles=("all",), keywords=("fotolijst", "photo frame", "cornice", "fotolijsten")),
    CategoryNode("home_decor_wall_art", "Quadri / wall art", parent="home_decor", group="home_decor", profiles=("all",), keywords=("wall art", "quadro", "poster", "fotografie")),
    CategoryNode("home_furniture", "Mobili", parent="home", group="home_furniture", profiles=("all",), keywords=("mobili", "furniture", "table", "chair")),
    CategoryNode("home_furniture_table", "Tavoli", parent="home_furniture", group="home_furniture", profiles=("all",), keywords=("tavolo", "table", "tisch", "pöytä", "neuvottelupöytä")),
    CategoryNode("home_furniture_chair", "Sedie", parent="home_furniture", group="home_furniture", profiles=("all",), keywords=("sedia", "chair", "stuhl", "tuoli")),
    CategoryNode("home_storage", "Contenitori / storage", parent="home", group="home_storage", profiles=("all",), keywords=("contenitore", "vorratsdose", "storage container", "aufbewahrungsdose")),
    CategoryNode("home_storage_container", "Contenitori casa/cucina", parent="home_storage", group="home_storage", profiles=("all",), keywords=("contenitore", "barattolo", "vorratsdose", "food container")),
    CategoryNode("fashion", "Moda", group="root", keywords=("moda", "fashion", "abbigliamento")),
    CategoryNode("fashion_clothing", "Abbigliamento", parent="fashion", group="fashion", profiles=("all",), keywords=("polo", "shirt", "t-shirt", "maglia", "ralph lauren")),
    CategoryNode("fashion_bag", "Borse / marsupi", parent="fashion", group="fashion", profiles=("all",), keywords=("borsa", "marsupio", "nerka", "saszetka", "handbag", "bag")),
    CategoryNode("bags", "Borse / zaini", group="root", keywords=("borsa", "zaino", "bag")),
    CategoryNode("school_bag", "Zaini scuola", parent="bags", group="bags", profiles=("all",), keywords=("skoletaske", "school bag", "zaino scuola", "schulranzen")),
    CategoryNode("sports", "Sport / tempo libero", group="root", keywords=("sport", "outdoor", "tempo libero")),
    CategoryNode("sports_billiards", "Biliardo", parent="sports", group="sports", profiles=("all",), keywords=("biljardbord", "billiard table", "pool table")),
    CategoryNode("sports_fishing_lure", "Esche pesca", parent="sports", group="sports", profiles=("all",), keywords=("wobbler", "fishing lure", "abu garcia", "esca artificiale")),
    CategoryNode("sports_fitness_equipment", "Fitness / attrezzi sportivi", parent="sports", group="sports", profiles=("all",), keywords=("tapis roulant", "treadmill", "løbebånd", "loebebaand", "speed rope", "sjippetov")),
    CategoryNode("toys", "Giochi / giocattoli", group="root", keywords=("giocattoli", "toys", "lego")),
    CategoryNode("toys_lego", "LEGO / minifigure", parent="toys", group="toys", profiles=("all",), keywords=("lego", "minifigure", "playmobil")),
    CategoryNode("toys_dollhouse", "Case delle bambole", parent="toys", group="toys", profiles=("all",), keywords=("casa de muñecas", "dollhouse", "doll house", "puppenhaus")),
    CategoryNode("baby_child", "Bambini / sicurezza", group="root", keywords=("bambini", "child", "baby", "seggiolino")),
    CategoryNode("baby_child_car_seat", "Seggiolini auto bambini", parent="baby_child", group="baby_child", profiles=("all",), keywords=("seggiolino auto", "fotelik", "turvakaukalo", "britax römer")),
    CategoryNode("vehicles", "Veicoli / ricambi", group="root", keywords=("auto", "moto", "ricambi", "vehicle")),
    CategoryNode("vehicle_car", "Auto complete", parent="vehicles", group="vehicles", profiles=("vehicle", "all"), keywords=("auto", "car", "opel astra", "bmw", "audi")),
    CategoryNode("vehicle_car_part", "Ricambi auto", parent="vehicles", group="vehicles", profiles=("vehicle", "all"), keywords=("ricambio auto", "car part", "kompresor klimatyzacji", "felgenschloss")),
    CategoryNode("vehicle_motorcycle_accessory", "Accessori moto", parent="vehicles", group="vehicles", profiles=("vehicle", "all"), keywords=("baule moto", "baul de moto", "top case", "motorradkoffer")),
    CategoryNode("music", "Musica / strumenti", group="root", keywords=("musica", "strumenti", "drums")),
    CategoryNode("music_drums", "Batterie / drums", parent="music", group="music", profiles=("all",), keywords=("batteria acustica", "drums", "custom drums")),
    CategoryNode("books_media", "Libri / media", group="root", keywords=("libri", "book", "media")),
    CategoryNode("books_media_book", "Libri", parent="books_media", group="books_media", profiles=("all",), keywords=("libro", "book", "buch", "livre")),
    CategoryNode("unknown", "Sconosciuto", group="system", keywords=()),
)


def category_map() -> dict[str, CategoryNode]:
    return {c.key: c for c in DEFAULT_CATEGORY_NODES}


def category_keys() -> list[str]:
    return [c.key for c in DEFAULT_CATEGORY_NODES]


def broad_queries_for_category(category_key: str, *, max_queries: int = 12) -> list[str]:
    node = category_map().get(category_key)
    if not node:
        return []
    return list(node.keywords[:max_queries])


def categories_for_profile(profile: str) -> list[str]:
    return [c.key for c in DEFAULT_CATEGORY_NODES if profile in c.profiles]


def seed_category_rows() -> list[dict]:
    return [
        {
            "category_key": c.key,
            "label": c.label,
            "parent_key": c.parent,
            "group_name": c.group,
            "keywords": list(c.keywords),
            "profiles": list(c.profiles),
        }
        for c in DEFAULT_CATEGORY_NODES
    ]
