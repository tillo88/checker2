#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import json
import re
from urllib.parse import urlparse

from spyengine.marketplace_harvest.store import MarketplaceCacheStore
from spyengine.marketplace_harvest.ingest_pipeline import simple_terms_for_category, is_category_or_nav_url, is_generic_category_title, normalize_listing_title, has_model_specificity
from spyengine.marketplace_harvest.canonicalize import canonicalize_product
from spyengine.wizard.knowledge_enrichment import search_web_with_diagnostics


STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "all", "view", "categories",
    "new", "used", "refurbished", "ricondizionato", "apple", "weeks",
    "just", "few", "left", "bestseller", "deal", "deals", "sale",
    "phone", "phones", "smartphone", "smartphones", "cellulari", "telefoni",
    "laptop", "laptops", "tablet", "tablets", "accessories", "accessori",
    "di", "da", "per", "con", "il", "la", "lo", "gli", "le", "un", "una",
}


def tokens(text: str) -> list[str]:
    out = []
    for t in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9+._-]{1,}", text or ""):
        tl = t.lower().strip("-_.")
        if len(tl) < 2 or tl in STOPWORDS:
            continue
        out.append(tl)
    return out


def build_verify_query(item: dict) -> str:
    title = normalize_listing_title(str(item.get("clean_title") or item.get("title") or "").strip())
    category = str(item.get("clean_category") or item.get("category") or "").strip()
    common = simple_terms_for_category(category)[:3]
    bits = [title]
    # Site/source in query helps verify product pages and avoids broad junk.
    url = str(item.get("url") or "")
    host = urlparse(url).netloc.replace("www.", "")
    if host:
        bits.append(host)
    bits.extend(common)
    return " ".join(x for x in bits if x).strip()



def evidence_tokens(title: str, url: str = "") -> list[str]:
    """Keep model numbers when the title is model-specific, but avoid prices/ratings."""

    raw = tokens(title)
    model_specific = has_model_specificity(title, url)

    out: list[str] = []
    for t in raw:
        if re.fullmatch(r"\d+[,.]?\d*", t):
            # Keep short/model-ish numbers only when the title has a model pattern:
            # iPhone 13, Pixel 8, iPad 9, Watch 8, T490, etc.
            if model_specific and len(t.replace(",", "").replace(".", "")) <= 4:
                out.append(t.replace(",", "."))
            continue
        out.append(t)
    return out


def product_slug_tokens(url: str) -> set[str]:
    path = urlparse(url).path.lower()
    path = re.sub(r"^.*?/p/", "", path)
    return set(tokens(path.replace("-", " ")))


def same_product_url_evidence(item_url: str, result_url: str) -> bool:
    if not item_url or not result_url:
        return False
    a = urlparse(item_url)
    b = urlparse(result_url)
    if a.netloc.replace("www.", "") != b.netloc.replace("www.", ""):
        return False
    return a.path.rstrip("/").lower() == b.path.rstrip("/").lower()


def score_evidence(item: dict, results: list[dict]) -> tuple[str, float, str, dict]:
    raw_title = str(item.get("clean_title") or item.get("title") or "")
    canonical = canonicalize_product(raw_title, str(item.get("clean_category") or item.get("category") or ""))
    title = canonical.title
    url = str(item.get("url") or "")
    clean_decision = str(item.get("clean_decision") or "")

    if is_category_or_nav_url(url):
        return "rejected", 0.98, "category_url_not_listing", {"results": results[:3], "matched_tokens": [], "normalized_title": title, "clean_decision": clean_decision}
    if is_generic_category_title(title) and not has_model_specificity(title, url):
        return "rejected", 0.96, "generic_category_title", {"results": results[:3], "matched_tokens": [], "normalized_title": title, "clean_decision": clean_decision}

    title_tokens = evidence_tokens(title, url)
    if not title_tokens:
        return "rejected", 0.05, "no_distinctive_title_tokens", {"results": results[:3], "matched_tokens": [], "normalized_title": title, "clean_decision": clean_decision}

    slug_tokens = product_slug_tokens(url)
    model_specific = has_model_specificity(title, url)
    best_score = 0.0; best = None; best_matches: list[str] = []; exact_product_url = False
    for r in results or []:
        result_url = str(r.get("url") or "")
        hay = " ".join(str(r.get(k) or "") for k in ("title", "snippet", "url")).lower()
        matches = [tok for tok in title_tokens if tok in hay]
        matches.extend([tok for tok in title_tokens if tok in slug_tokens])
        matches = sorted(set(matches))
        token_score = len(matches) / max(1, len(set(title_tokens)))
        if same_product_url_evidence(url, result_url):
            exact_product_url = True
            token_score = max(token_score, 0.95)
        if token_score > best_score:
            best_score = token_score; best = r; best_matches = matches

    evidence = {"normalized_title": title, "canonical_category": canonical.category, "title_tokens": title_tokens, "slug_tokens": sorted(slug_tokens), "matched_tokens": best_matches, "best_result": best, "exact_product_url": exact_product_url, "clean_decision": clean_decision, "canonical_warnings": canonical.warnings, "results": results[:5]}

    if clean_decision == "reject" and model_specific and exact_product_url and len(best_matches) >= 1:
        return "verified_conflict", 0.93, "clean_reject_but_same_product_url_model_match", evidence
    if model_specific and exact_product_url and len(best_matches) >= 1:
        return "verified", 0.97, "same_product_url_model_match", evidence
    if model_specific and best_score >= 0.55 and len(best_matches) >= 2:
        return "verified", min(0.98, 0.58 + best_score * 0.4), "web_model_title_match", evidence
    if best_score >= 0.80 and len(best_matches) >= 3:
        return "verified", min(0.96, 0.55 + best_score * 0.35), "web_title_match", evidence
    if results:
        return "uncertain", min(0.49, max(0.25, best_score)), "weak_web_evidence", evidence
    return "rejected", 0.10, "no_web_evidence", evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify fetched marketplace listings online before catalog promotion.")
    parser.add_argument("--db", default="data/marketplace_cache/marketplace.sqlite")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--enqueue-missing", action="store_true")
    parser.add_argument("--include-rejected-clean", action="store_true", help="verify also cleaning-decision=reject records")
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    store = MarketplaceCacheStore(args.db)
    try:
        if args.enqueue_missing:
            added = store.enqueue_online_verifications_for_unverified(
                limit=max(args.limit, 1_000_000),
                include_rejected_clean=args.include_rejected_clean,
            )
            print(f"[enqueue-online] added={added}")

        pending = store.pending_online_verifications(limit=args.limit)
        print(json.dumps({"db": str(store.path), "selected": len(pending), "summary": store.online_verification_summary()}, ensure_ascii=False, indent=2))

        for item in pending:
            query = build_verify_query(item)
            results, diag = search_web_with_diagnostics(query, max_results=args.max_results, timeout=args.timeout)
            status, confidence, reason, evidence = score_evidence(item, results)
            evidence["diagnostics"] = diag
            print(json.dumps({
                "verification_id": item["verification_id"],
                "title": item["title"],
                "query": query,
                "status": status,
                "confidence": confidence,
                "reason": reason,
            }, ensure_ascii=False))

            if not args.dry_run:
                store.mark_online_verification_done(
                    verification_id=int(item["verification_id"]),
                    status=status,
                    query=query,
                    confidence=confidence,
                    reason=reason,
                    evidence=evidence,
                )

        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
