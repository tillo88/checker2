from __future__ import annotations
import json, re, unicodedata
from typing import Any, Optional


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return unicodedata.normalize("NFKC", str(text)).lower().strip()


def _to_float(num: str, default: float = 999.0) -> float:
    try:
        num = str(num).strip().replace("\u00a0", " ").replace(" ", "")
        if "," in num and "." in num:
            # 1.234,56 -> 1234.56
            if num.rfind(",") > num.rfind("."):
                num = num.replace(".", "").replace(",", ".")
            else:
                num = num.replace(",", "")
        else:
            num = num.replace(",", ".")
        return float(num)
    except Exception:
        return default


def parse_euro_price(text: str | None, default: float = 999.0) -> float:
    """Prefer explicit prices followed by €, avoiding leading badge numbers like '1Lenovo'."""
    if not text:
        return default
    raw = str(text).replace("\u00a0", " ")
    matches = re.findall(r"(\d{1,6}(?:[.,]\d{1,2})?)\s*€", raw)
    if matches:
        return _to_float(matches[0], default)
    matches = re.findall(r"€\s*(\d{1,6}(?:[.,]\d{1,2})?)", raw)
    if matches:
        return _to_float(matches[0], default)
    return default


def parse_price(text: str | None, default: float = 999.0) -> float:
    if not text:
        return default
    explicit = parse_euro_price(text, None)
    if explicit is not None:
        return explicit
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(text))
    if not m:
        return default
    return _to_float(m.group(1), default)


def extract_json_object(text: str | None) -> Optional[dict[str, Any]]:
    if not text:
        return None
    cleaned = text.strip()
    if "```" in cleaned:
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return None
