from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class ProductIdentifier:
    identifier_type: str
    value: str
    confidence: float = 0.8
    source: str = "listing_text"


_ASIN_LABELED_RE = re.compile(r"\bASIN[:\s#-]*([A-Z0-9]{10})\b", re.I)
_EAN_RE = re.compile(r"\b(?:EAN|GTIN|UPC|BARCODE|CODICE\s*A\s*BARRE|CODICE\s*EAN)[:\s#-]*([0-9]{8,14})\b", re.I)
_EAN_BARE_RE = re.compile(r"\b([0-9]{12,14})\b")
_MPN_RE = re.compile(r"\b(?:MPN|P/?N|PN|PART\s*(?:NO\.?|NUMBER)?|SKU|COD(?:ICE)?\s*(?:PRODUTTORE|MODELLO)?|MODEL\s*(?:NO\.?|CODE)?|FRU)[:\s#-]*([A-Z0-9][A-Z0-9._/+:-]{3,40})\b", re.I)
_LABELESS_PART_RE = re.compile(r"\b([A-Z]{2,8}[A-Z0-9]{1,12}[-_/][A-Z0-9][A-Z0-9._/+:-]{2,32})\b")


def normalize_identifier_value(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).upper()


def _valid_ean_checksum(code: str) -> bool:
    if not code.isdigit() or len(code) not in {8, 12, 13, 14}:
        return False
    digits = [int(c) for c in code]
    check = digits[-1]
    body = digits[:-1]
    total = 0
    for i, d in enumerate(reversed(body)):
        total += d * (3 if i % 2 == 0 else 1)
    return ((10 - (total % 10)) % 10) == check


def extract_product_identifiers(text: str) -> list[ProductIdentifier]:
    text = text or ""
    out: list[ProductIdentifier] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, value: str, confidence: float) -> None:
        value = normalize_identifier_value(value)
        if not value: return
        key = (kind, value)
        if key in seen: return
        seen.add(key)
        out.append(ProductIdentifier(kind, value, confidence))

    for m in _MPN_RE.finditer(text): add("mpn", m.group(1), 0.90)
    for m in _EAN_RE.finditer(text):
        code = normalize_identifier_value(m.group(1))
        add("gtin" if len(code) == 14 else "ean_upc", code, 0.95 if _valid_ean_checksum(code) else 0.75)
    for m in _EAN_BARE_RE.finditer(text):
        code = normalize_identifier_value(m.group(1))
        if _valid_ean_checksum(code): add("gtin" if len(code) == 14 else "ean_upc", code, 0.88)
    for m in _ASIN_LABELED_RE.finditer(text): add("asin", m.group(1), 0.90)
    for m in _LABELESS_PART_RE.finditer(text):
        token = normalize_identifier_value(m.group(1))
        if token.startswith(("HTTP", "HTTPS", "WWW")): continue
        add("sku_candidate", token, 0.62)
    return out


def identifiers_to_dicts(items: Iterable[ProductIdentifier]) -> list[dict]:
    return [{"identifier_type": i.identifier_type, "value": i.value, "confidence": i.confidence, "source": i.source} for i in items]
