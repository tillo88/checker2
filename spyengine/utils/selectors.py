from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime


def _count(locator) -> int:
    try:
        return locator.count()
    except Exception:
        return 0


def safe_inner_text(locator, timeout: int = 1500) -> str:
    try:
        if _count(locator) <= 0:
            return ""
        return (locator.first.inner_text(timeout=timeout) or "").strip()
    except Exception:
        return ""


def safe_text_content(locator, timeout: int = 1500) -> str:
    try:
        if _count(locator) <= 0:
            return ""
        return (locator.first.text_content(timeout=timeout) or "").strip()
    except Exception:
        return ""


def _safe_attr_locator(locator, attr: str, timeout: int = 1500) -> str:
    try:
        if _count(locator) <= 0:
            return ""
        val = locator.first.get_attribute(attr, timeout=timeout)
        return (val or "").strip()
    except Exception:
        return ""


def safe_text(scope, selectors: list[str] | tuple[str, ...] | str | None = None, timeout: int = 1500, min_len: int = 1) -> str:
    """
    Compatibile con:
    - safe_text(locator)
    - safe_text(scope, ["selector1", "selector2"], min_len=2)
    """
    if selectors is None:
        txt = safe_inner_text(scope, timeout=timeout) or safe_text_content(scope, timeout=timeout)
        return txt if len(txt.strip()) >= min_len else ""

    if isinstance(selectors, str):
        selectors = [selectors]

    for sel in selectors:
        txt = safe_inner_text(scope.locator(sel), timeout=timeout) or safe_text_content(scope.locator(sel), timeout=timeout)
        if len(txt.strip()) >= min_len:
            return txt.strip()
    return ""


def safe_attr(scope, selectors_or_attr, attr: str | None = None, timeout: int = 1500) -> str:
    """
    Compatibile con:
    - safe_attr(locator, "href")
    - safe_attr(scope, ["a[href]"], "href")
    """
    if attr is None:
        return _safe_attr_locator(scope, selectors_or_attr, timeout=timeout)

    selectors = selectors_or_attr
    if isinstance(selectors, str):
        selectors = [selectors]

    for sel in selectors:
        val = _safe_attr_locator(scope.locator(sel), attr, timeout=timeout)
        if val:
            return val
    return ""


def first_text(scope, selectors: list[str], timeout: int = 1500, min_len: int = 1) -> str:
    return safe_text(scope, selectors, timeout=timeout, min_len=min_len)


def first_attr(scope, selectors: list[str], attr: str, timeout: int = 1500) -> str:
    return safe_attr(scope, selectors, attr, timeout=timeout)


def parse_euro_price(text: str | None, default: float = 999.0) -> float:
    if not text:
        return default

    patterns = [
        r"(\d{1,5}(?:[.,]\d{1,2})?)\s*(?:€|eur)",
        r"(?:€|eur)\s*(\d{1,5}(?:[.,]\d{1,2})?)",
    ]

    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except Exception:
                pass

    nums = re.findall(r"\d{2,5}(?:[.,]\d{1,2})?", text)
    for n in nums:
        try:
            return float(n.replace(",", "."))
        except Exception:
            continue
    return default


def normalize_url(href: str, base: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return base.rstrip("/") + href
    return base.rstrip("/") + "/" + href


def debug_snapshot(page, label: str, debug_dir: str = "data/debug", logger=None) -> None:
    try:
        out = Path(debug_dir)
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", label)[:80]
        html_path = out / f"{stamp}_{safe}.html"
        png_path = out / f"{stamp}_{safe}.png"
        html_path.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(png_path), full_page=True)
        if logger:
            logger.warning(f"Debug snapshot salvato: {html_path} / {png_path}")
    except Exception as e:
        if logger:
            logger.warning(f"Debug snapshot fallito: {e}")


def extract_links_from_scope(scope, base_url: str) -> list[tuple[str, str]]:
    out = []
    try:
        anchors = scope.locator("a")
        count = anchors.count()
        for i in range(min(count, 20)):
            a = anchors.nth(i)
            href = (a.get_attribute("href") or "").strip()
            if not href:
                continue
            text = ""
            try:
                text = (a.inner_text(timeout=800) or "").strip()
            except Exception:
                pass
            out.append((normalize_url(href, base_url), text))
    except Exception:
        pass
    return out


# Alias esplicito per eventuali import futuri.
safe_attr_first = safe_attr
