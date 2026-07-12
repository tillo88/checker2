#!/usr/bin/env python3
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as td:
    pkg = Path(td) / "spyengine" / "marketplace_harvest"
    pkg.mkdir(parents=True)
    (Path(td) / "spyengine" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(ROOT / "canonicalize.py", pkg / "canonicalize.py")
    shutil.copy2(ROOT / "ingest_pipeline.py", pkg / "ingest_pipeline.py")
    sys.path.insert(0, td)
    from spyengine.marketplace_harvest.ingest_pipeline import deterministic_clean_decision, normalize_listing_title

    assert normalize_listing_title("Pochi rimasti iPhone 16 4,9 569,00 € 849,00 € (Nuovo)") == "iPhone 16"
    d = deterministic_clean_decision(
        "Pochi rimasti iPhone 16 4,9 569,00 € 849,00 € (Nuovo)",
        "Smartphone",
        {"reason": "price_card"},
        "https://www.refurbed.it/p/iphone-16/",
    )
    assert d.normalized_title == "iPhone 16"
    assert d.decision in {"accept", "uncertain"}
print("OK")
