from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from .product_relations import ensure_relation_schema, relations_for_entity


MARKETING_NOISE = {
    "affare",
    "affarone",
    "best price",
    "imperdibile",
    "offerta",
    "ottima offerta",
    "prezzo bomba",
    "promo",
    "super offerta",
    "vendo",
}

CONDITION_TERMS = {
    "nuovo": "new",
    "nuova": "new",
    "new": "new",
    "sigillato": "new_sealed",
    "sealed": "new_sealed",
    "ricondizionato": "refurbished",
    "ricondiziato": "refurbished",
    "refurbished": "refurbished",
    "usato": "used",
    "used": "used",
    "difettoso": "for_parts",
    "non funzionante": "for_parts",
    "for parts": "for_parts",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_product_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def informative_tokens(value: Any) -> list[str]:
    normalized = normalize_product_text(value)
    for phrase in sorted(MARKETING_NOISE, key=len, reverse=True):
        normalized = re.sub(rf"\b{re.escape(phrase)}\b", " ", normalized)
    return [token for token in normalized.split() if len(token) > 1]


def token_signature(value: Any) -> str:
    return " ".join(sorted(set(informative_tokens(value))))


def extract_condition(title: str, description: str = "") -> str:
    combined = normalize_product_text(f"{title} {description}")
    matches = [canonical for term, canonical in CONDITION_TERMS.items() if normalize_product_text(term) in combined]
    if "for_parts" in matches:
        return "for_parts"
    if "refurbished" in matches:
        return "refurbished"
    if "new_sealed" in matches:
        return "new_sealed"
    if "new" in matches:
        return "new"
    if "used" in matches:
        return "used"
    return "unknown"


def ensure_product_knowledge_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS product_search_terms (
            id INTEGER PRIMARY KEY,
            family_id INTEGER,
            variant_id INTEGER,
            entity_type TEXT NOT NULL,
            term TEXT NOT NULL,
            term_norm TEXT NOT NULL,
            token_signature TEXT NOT NULL,
            language TEXT,
            term_kind TEXT NOT NULL,
            source TEXT,
            confidence REAL NOT NULL DEFAULT 0.5,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(family_id, variant_id, term_norm, term_kind)
        );

        CREATE TABLE IF NOT EXISTS product_search_term_tokens (
            term_id INTEGER NOT NULL,
            token TEXT NOT NULL,
            PRIMARY KEY(term_id, token),
            FOREIGN KEY(term_id) REFERENCES product_search_terms(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS product_evidence (
            id INTEGER PRIMARY KEY,
            family_id INTEGER,
            variant_id INTEGER,
            evidence_type TEXT NOT NULL,
            field_name TEXT,
            value_json TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_ref TEXT,
            excerpt TEXT,
            language TEXT,
            confidence REAL NOT NULL DEFAULT 0.5,
            content_hash TEXT,
            observed_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(family_id, variant_id, evidence_type, field_name, value_json, source_ref)
        );

        CREATE TABLE IF NOT EXISTS product_relations (
            id INTEGER PRIMARY KEY,
            subject_family_id INTEGER,
            subject_variant_id INTEGER,
            relation_type TEXT NOT NULL,
            object_family_id INTEGER,
            object_variant_id INTEGER,
            source TEXT,
            confidence REAL NOT NULL DEFAULT 0.5,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS product_resolution_reviews (
            id INTEGER PRIMARY KEY,
            listing_id INTEGER,
            title TEXT NOT NULL,
            description_sample TEXT,
            selected_family_id INTEGER,
            selected_variant_id INTEGER,
            confidence REAL NOT NULL,
            status TEXT NOT NULL,
            candidates_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            resolver_version TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS product_alias_quality_reviews (
            alias_id INTEGER PRIMARY KEY,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            confidence REAL NOT NULL,
            reviewed_at TEXT NOT NULL,
            FOREIGN KEY(alias_id) REFERENCES product_aliases(id) ON DELETE CASCADE
        );


        CREATE INDEX IF NOT EXISTS idx_product_search_terms_norm
            ON product_search_terms(term_norm);
        CREATE INDEX IF NOT EXISTS idx_product_search_tokens_token
            ON product_search_term_tokens(token, term_id);
        CREATE INDEX IF NOT EXISTS idx_product_evidence_entity
            ON product_evidence(family_id, variant_id, field_name);
        CREATE INDEX IF NOT EXISTS idx_product_relations_subject
            ON product_relations(subject_family_id, subject_variant_id, relation_type);
        CREATE INDEX IF NOT EXISTS idx_product_alias_quality_decision
            ON product_alias_quality_reviews(decision, alias_id);
        """
    )
    ensure_relation_schema(con)
    con.commit()


def _upsert_search_term(
    con: sqlite3.Connection,
    *,
    family_id: int | None,
    variant_id: int | None,
    entity_type: str,
    term: str,
    term_kind: str,
    source: str,
    confidence: float,
    language: str | None = None,
) -> int | None:
    norm = normalize_product_text(term)
    tokens = informative_tokens(norm)
    if not norm or not tokens:
        return None
    now = utc_now()
    existing = con.execute(
        """
        SELECT id, confidence FROM product_search_terms
        WHERE family_id IS ? AND variant_id IS ? AND term_norm=? AND term_kind=?
        """,
        (family_id, variant_id, norm, term_kind),
    ).fetchone()
    if existing:
        term_id = int(existing[0])
        con.execute(
            """
            UPDATE product_search_terms
            SET confidence=?, source=COALESCE(source, ?), updated_at=?
            WHERE id=?
            """,
            (max(float(existing[1] or 0.0), float(confidence)), source, now, term_id),
        )
        con.execute("DELETE FROM product_search_term_tokens WHERE term_id=?", (term_id,))
        con.executemany(
            "INSERT OR IGNORE INTO product_search_term_tokens(term_id, token) VALUES (?, ?)",
            [(term_id, token) for token in sorted(set(tokens))],
        )
        return term_id
    con.execute(
        """
        INSERT INTO product_search_terms(
            family_id, variant_id, entity_type, term, term_norm, token_signature,
            language, term_kind, source, confidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(family_id, variant_id, term_norm, term_kind) DO UPDATE SET
            confidence = MAX(product_search_terms.confidence, excluded.confidence),
            source = COALESCE(product_search_terms.source, excluded.source),
            updated_at = excluded.updated_at
        """,
        (
            family_id,
            variant_id,
            entity_type,
            term,
            norm,
            token_signature(norm),
            language,
            term_kind,
            source,
            max(0.0, min(float(confidence), 1.0)),
            now,
            now,
        ),
    )
    row = con.execute(
        """
        SELECT id FROM product_search_terms
        WHERE family_id IS ? AND variant_id IS ? AND term_norm=? AND term_kind=?
        """,
        (family_id, variant_id, norm, term_kind),
    ).fetchone()
    if not row:
        return None
    term_id = int(row[0])
    con.execute("DELETE FROM product_search_term_tokens WHERE term_id=?", (term_id,))
    con.executemany(
        "INSERT OR IGNORE INTO product_search_term_tokens(term_id, token) VALUES (?, ?)",
        [(term_id, token) for token in sorted(set(tokens))],
    )
    return term_id


def rebuild_product_search_index(con: sqlite3.Connection) -> dict[str, int]:
    ensure_product_knowledge_schema(con)
    counts = {"families": 0, "variants": 0, "aliases": 0, "identifiers": 0}
    con.execute("DELETE FROM product_search_term_tokens")
    con.execute("DELETE FROM product_search_terms")

    for row in con.execute("SELECT id, brand, family_name, confidence FROM product_families"):
        family_id = int(row[0])
        brand = str(row[1] or "").strip()
        name = str(row[2] or "").strip()
        label = f"{brand} {name}".strip()
        if _upsert_search_term(
            con,
            family_id=family_id,
            variant_id=None,
            entity_type="family",
            term=label,
            term_kind="canonical_name",
            source="product_families",
            confidence=float(row[3] or 0.5),
        ):
            counts["families"] += 1

    for row in con.execute(
        """
        SELECT v.id, v.family_id, f.brand, f.family_name, v.variant_name, v.confidence
        FROM product_variants v JOIN product_families f ON f.id=v.family_id
        """
    ):
        variant_id, family_id = int(row[0]), int(row[1])
        label = " ".join(str(x or "").strip() for x in row[2:5]).strip()
        if _upsert_search_term(
            con,
            family_id=family_id,
            variant_id=variant_id,
            entity_type="variant",
            term=label,
            term_kind="canonical_name",
            source="product_variants",
            confidence=float(row[5] or 0.5),
        ):
            counts["variants"] += 1

    for row in con.execute(
        """
        SELECT a.family_id, a.variant_id, COALESCE(a.family_id, v.family_id),
               a.alias, a.source, a.confidence
        FROM product_aliases a
        LEFT JOIN product_variants v ON v.id=a.variant_id
        LEFT JOIN product_alias_quality_reviews q ON q.alias_id=a.id
        WHERE COALESCE(q.decision, '') <> 'reject'
        """
    ):
        family_id = int(row[2]) if row[2] is not None else None
        variant_id = int(row[1]) if row[1] is not None else None
        if _upsert_search_term(
            con,
            family_id=family_id,
            variant_id=variant_id,
            entity_type="variant" if variant_id else "family",
            term=str(row[3]),
            term_kind="alias",
            source=str(row[4] or "product_aliases"),
            confidence=float(row[5] or 0.5),
        ):
            counts["aliases"] += 1

    # Identifiers are indexed as exact high-confidence terms.
    for row in con.execute(
        """
        SELECT i.family_id, i.variant_id, COALESCE(i.family_id, v.family_id),
               i.identifier_value, i.identifier_type, i.source, i.confidence
        FROM product_identifiers i LEFT JOIN product_variants v ON v.id=i.variant_id
        """
    ):
        family_id = int(row[2]) if row[2] is not None else None
        variant_id = int(row[1]) if row[1] is not None else None
        if _upsert_search_term(
            con,
            family_id=family_id,
            variant_id=variant_id,
            entity_type="variant" if variant_id else "family",
            term=str(row[3]),
            term_kind=f"identifier:{row[4]}",
            source=str(row[5] or "product_identifiers"),
            confidence=max(0.9, float(row[6] or 0.5)),
        ):
            counts["identifiers"] += 1

    con.commit()
    return counts


@dataclass
class ResolutionEvidence:
    source: str
    term: str
    weight: float
    detail: str


@dataclass
class ProductCandidate:
    family_id: int
    variant_id: int | None
    category: str
    brand: str
    family_name: str
    variant_name: str
    score: float
    confidence: float
    evidence: list[ResolutionEvidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductResolution:
    title_normalized: str
    description_normalized: str
    condition: str
    status: str
    confidence: float
    selected: ProductCandidate | None
    candidates: list[ProductCandidate]
    relations: list[dict[str, Any]] = field(default_factory=list)
    resolver_version: str = "catalog-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title_normalized": self.title_normalized,
            "description_normalized": self.description_normalized,
            "condition": self.condition,
            "status": self.status,
            "confidence": self.confidence,
            "selected": self.selected.to_dict() if self.selected else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "relations": self.relations,
            "resolver_version": self.resolver_version,
        }


def _candidate_terms(
    con: sqlite3.Connection,
    tokens: Iterable[str],
    *,
    limit: int = 250,
) -> list[sqlite3.Row]:
    unique = sorted(set(tokens))
    if not unique:
        return []
    placeholders = ",".join("?" for _ in unique)
    sql = f"""
        SELECT st.*, f.brand AS entity_brand, f.family_name AS entity_family,
               COUNT(DISTINCT tok.token) AS matched_tokens
        FROM product_search_term_tokens tok
        JOIN product_search_terms st ON st.id=tok.term_id
        JOIN product_families f ON f.id=st.family_id
        WHERE tok.token IN ({placeholders})
        GROUP BY st.id
        ORDER BY matched_tokens DESC, st.confidence DESC
        LIMIT ?
    """
    return list(con.execute(sql, [*unique, max(1, int(limit))]))


def _entity_details(con: sqlite3.Connection, family_id: int, variant_id: int | None) -> sqlite3.Row | None:
    return con.execute(
        """
        SELECT f.category, COALESCE(f.brand, ''), f.family_name,
               COALESCE(v.variant_name, ''), f.id, v.id
        FROM product_families f
        LEFT JOIN product_variants v ON v.id=? AND v.family_id=f.id
        WHERE f.id=?
        """,
        (variant_id, family_id),
    ).fetchone()


def resolve_product(
    con: sqlite3.Connection,
    title: str,
    description: str = "",
    *,
    select_threshold: float = 0.72,
    ambiguity_margin: float = 0.08,
    max_candidates: int = 5,
) -> ProductResolution:
    title_norm = normalize_product_text(title)
    description_norm = normalize_product_text(description)
    title_tokens = set(informative_tokens(title))
    description_tokens = set(informative_tokens(description))
    combined_tokens = title_tokens | description_tokens

    if not table_present(con, "product_search_terms"):
        return ProductResolution(
            title_norm,
            description_norm,
            extract_condition(title, description),
            "catalog_index_missing",
            0.0,
            None,
            [],
        )

    accumulated: dict[tuple[int, int | None], dict[str, Any]] = {}
    for term in _candidate_terms(con, combined_tokens):
        family_id = int(term["family_id"]) if term["family_id"] is not None else None
        if family_id is None:
            continue
        variant_id = int(term["variant_id"]) if term["variant_id"] is not None else None
        term_tokens = set(informative_tokens(term["term_norm"]))
        if not term_tokens:
            continue
        identity_tokens = set(informative_tokens(f"{term['entity_brand']} {term['entity_family']}"))
        term_kind = str(term["term_kind"])


        title_overlap = len(term_tokens & title_tokens) / len(term_tokens)
        desc_overlap = len(term_tokens & description_tokens) / len(term_tokens)
        title_precision = len(term_tokens & title_tokens) / max(1, len(title_tokens))
        desc_precision = len(term_tokens & description_tokens) / max(1, len(description_tokens))
        exact_title = term["term_norm"] in title_norm
        exact_description = bool(description_norm and term["term_norm"] in description_norm)
        identifier = term_kind.startswith("identifier:")

        confidence = float(term["confidence"] or 0.5)
        weight = 0.0
        source = ""
        detail = ""
        if identifier and (exact_title or exact_description):
            weight = 1.25 * confidence
            source = "identifier"
            detail = "identificatore esatto"
        elif exact_title:
            weight = (0.78 + min(0.18, 0.03 * len(term_tokens))) * confidence
            source = "title"
            detail = "alias/nome esatto nel titolo"
        elif title_overlap >= 0.6:
            weight = (0.62 * title_overlap + 0.18 * title_precision) * confidence
            source = "title"
            detail = f"token titolo {len(term_tokens & title_tokens)}/{len(term_tokens)}"
        elif exact_description:
            weight = 0.48 * confidence
            source = "description"
            detail = "alias/nome esatto nella descrizione"
        elif desc_overlap >= 0.75:
            weight = (0.34 * desc_overlap + 0.08 * desc_precision) * confidence
            source = "description"
            detail = f"token descrizione {len(term_tokens & description_tokens)}/{len(term_tokens)}"

        # A one-token alias that is unrelated to the canonical family is likely
        # contaminated learning (for example "iphone" attached to a Pixel).
        if term_kind == "alias" and len(term_tokens) == 1 and not term_tokens.issubset(identity_tokens):
            weight *= 0.15
            detail += "; alias incoerente con la famiglia"
        if weight <= 0:
            continue
        key = (family_id, variant_id)
        bucket = accumulated.setdefault(key, {"evidence": []})
        # Repeated synonyms are retained as explanation but receive diminishing weight below.
        bucket["evidence"].append(
            ResolutionEvidence(source, str(term["term"]), round(weight, 4), detail)
        )

    candidates: list[ProductCandidate] = []
    for (family_id, variant_id), bucket in accumulated.items():
        details = _entity_details(con, family_id, variant_id)
        if not details:
            continue
        unique_evidence = sorted(bucket["evidence"], key=lambda ev: ev.weight, reverse=True)
        weights = [ev.weight for ev in unique_evidence]
        raw_score = weights[0]
        if len(weights) > 1:
            raw_score += sum(weights[1:3]) * 0.22
        raw_score = min(1.25, raw_score)
        confidence = min(0.99, 1.0 - math.exp(-1.75 * raw_score))
        candidates.append(
            ProductCandidate(
                family_id=family_id,
                variant_id=variant_id,
                category=str(details[0] or "unknown"),
                brand=str(details[1] or ""),
                family_name=str(details[2] or ""),
                variant_name=str(details[3] or ""),
                score=round(raw_score, 4),
                confidence=round(confidence, 4),
                evidence=unique_evidence[:8],
            )
        )

    candidates.sort(key=lambda candidate: (candidate.score, candidate.confidence), reverse=True)
    candidates = candidates[: max(1, int(max_candidates))]
    top = candidates[0] if candidates else None
    second = candidates[1] if len(candidates) > 1 else None
    margin = (top.confidence - second.confidence) if top and second else (top.confidence if top else 0.0)

    strong_identifier = bool(
        top and any(ev.source == "identifier" and ev.weight >= 0.9 for ev in top.evidence)
    )
    strong_specific_title = bool(
        top
        and any(ev.source == "title" and "esatto" in ev.detail and len(informative_tokens(ev.term)) >= 3 for ev in top.evidence)
        and (not second or top.score - second.score >= 0.04)
    )
    strong_complete_title = bool(
        top
        and any(
            ev.source == "title" and len(informative_tokens(ev.term)) >= 3
            and set(informative_tokens(ev.term)).issubset(title_tokens) for ev in top.evidence
        )
        and (not second or top.score - second.score >= 0.04)
    )
    selected = top if top and top.confidence >= select_threshold and (margin >= ambiguity_margin or strong_identifier) else None
    if top and top.confidence >= select_threshold and strong_specific_title:
        selected = top
    if top and top.confidence >= select_threshold and strong_complete_title:
        selected = top
    if not candidates:
        status = "unresolved"
    elif selected:
        status = "resolved"
    else:
        status = "ambiguous"
    return ProductResolution(
        title_normalized=title_norm,
        description_normalized=description_norm,
        condition=extract_condition(title, description),
        status=status,
        confidence=round(top.confidence if top else 0.0, 4),
        selected=selected,
        candidates=candidates,
        relations=(
            relations_for_entity(con, selected.family_id, selected.variant_id) if selected else []
        ),
    )


def table_present(con: sqlite3.Connection, table: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    )


def resolution_json(resolution: ProductResolution) -> str:
    return json.dumps(resolution.to_dict(), ensure_ascii=False, indent=2)
