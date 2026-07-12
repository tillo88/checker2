from __future__ import annotations

import re
from typing import Any

from .canonicalize import parse_euro_number


_PRICE_RE = re.compile(
    r"(?:(€|eur|euro|chf|£|gbp|\$|usd)\s*)?([0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{1,2})?|[0-9]{1,8}(?:[.,][0-9]{1,2})?)\s*(€|eur|euro|chf|£|gbp|\$|usd)?",
    re.I,
)

_CURRENCY_MAP = {
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "chf": "CHF",
    "£": "GBP",
    "gbp": "GBP",
    "$": "USD",
    "usd": "USD",
}


def parse_price(text: str) -> tuple[float | None, str]:
    text = text or ""
    explicit: list[tuple[float, str]] = []
    for match in _PRICE_RE.finditer(text):
        left, number, right = match.groups()
        currency_token = (left or right or "").lower()
        if not currency_token:
            continue
        value = parse_euro_number(number)
        if value is None:
            continue
        explicit.append((value, _CURRENCY_MAP.get(currency_token, currency_token.upper())))
    if not explicit:
        return None, ""
    for value, currency in explicit:
        if value > 5:
            return value, currency
    return explicit[0]


def _numbers_for_unit(text: str, unit_pattern: str) -> list[float]:
    out: list[float] = []
    # Wrap alternatives. Without grouping, "v|volt" made "7801 View" match as 7801V.
    pattern = rf"(\d+(?:[.,]\d+)?)\s*(?:{unit_pattern})\b"
    for m in re.finditer(pattern, text, flags=re.I):
        try:
            out.append(float(m.group(1).replace(",", ".")))
        except ValueError:
            pass
    return out



def _filter_contextual_specs(text: str, specs: dict[str, Any]) -> dict[str, Any]:
    tl = (text or "").lower()
    out = dict(specs or {})
    if re.search(r"\bwd19tb\b", tl):
        out.pop("tb_values", None)
    if "inches" in out and not re.search(r'(?:"|inch|inches|pollici|display|schermo|monitor|screen)', tl):
        out.pop("inches", None)
    if "inches" in out and out.get("inches"):
        try:
            vals = [float(v) for v in out.get("inches") or []]
            if vals and max(vals) <= 5.0 and not re.search(r'(?:"|inch|inches|pollici)', tl):
                out.pop("inches", None)
        except Exception:
            pass
    return out

def extract_specs_from_text(text: str) -> dict[str, Any]:
    """Extract broad technical hints from a title/snippet.

    The harvester stores these as reusable facts. Runtime filters can then
    answer future requests like ">=16GB VRAM" from cache before hitting web.
    """

    t = text or ""
    tl = t.lower()
    specs: dict[str, Any] = {}

    gb_values = _numbers_for_unit(tl, r"gb|gib")
    tb_values = _numbers_for_unit(tl, r"tb|tib")
    if gb_values:
        specs["gb_values"] = sorted(set(gb_values))
    if tb_values:
        specs["tb_values"] = sorted(set(tb_values))

    # VRAM: value close to VRAM/GDDR/GPU words, or common GPU memory title pattern.
    vram_values: list[float] = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(gb|gib)\s*(?:vram|gddr|gpu|scheda video|graphics|video)", tl, flags=re.I):
        vram_values.append(float(m.group(1).replace(",", ".")))
    for m in re.finditer(r"(?:vram|gddr\d*|gpu|scheda video|graphics|video).{0,24}?(\d+(?:[.,]\d+)?)\s*(gb|gib)", tl, flags=re.I):
        vram_values.append(float(m.group(1).replace(",", ".")))
    if vram_values:
        specs["vram_gb_values"] = sorted(set(vram_values))

    ram_values: list[float] = []
    for m in re.finditer(r"(?:ram|memoria|ddr[345]).{0,24}?(\d+(?:[.,]\d+)?)\s*(gb|gib)", tl, flags=re.I):
        ram_values.append(float(m.group(1).replace(",", ".")))
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(gb|gib).{0,24}?(?:ram|memoria|ddr[345])", tl, flags=re.I):
        ram_values.append(float(m.group(1).replace(",", ".")))
    if ram_values:
        specs["ram_gb_values"] = sorted(set(ram_values))

    ddr = sorted(set(re.findall(r"\bddr[345]\b", tl)))
    if ddr:
        specs["ddr"] = ddr

    volts = _numbers_for_unit(tl, r"v|volt")
    if volts:
        specs["volts"] = sorted(set(volts))

    hz = _numbers_for_unit(tl, r"hz")
    if hz:
        specs["hz"] = sorted(set(hz))

    inches = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(?:\"|pollici|inch|inches)\b", tl, flags=re.I):
        try:
            inches.append(float(m.group(1).replace(",", ".")))
        except ValueError:
            pass
    if inches:
        specs["inches"] = sorted(set(inches))

    return _filter_contextual_specs(t, specs)
