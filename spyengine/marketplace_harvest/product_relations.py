from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


RELATION_TYPES = {
    "accessory_for",
    "compatible_with",
    "incompatible_with",
    "often_bundled_with",
    "predecessor_of",
    "replacement_for",
    "requires",
    "successor_of",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_relation_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
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
        CREATE INDEX IF NOT EXISTS idx_product_relations_subject
            ON product_relations(subject_family_id, subject_variant_id, relation_type);
        CREATE INDEX IF NOT EXISTS idx_product_relations_object
            ON product_relations(object_family_id, object_variant_id, relation_type);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_product_relations_edge
            ON product_relations(
                COALESCE(subject_family_id, -1), COALESCE(subject_variant_id, -1),
                relation_type,
                COALESCE(object_family_id, -1), COALESCE(object_variant_id, -1),
                COALESCE(source, '')
            );
        """
    )


def resolve_entity_ref(con: sqlite3.Connection, ref: dict[str, Any]) -> tuple[int, int | None]:
    family_key = str(ref.get("family_key") or "").strip()
    if not family_key:
        raise ValueError("relation endpoint senza family_key")
    family = con.execute(
        "SELECT id FROM product_families WHERE family_key=?", (family_key,)
    ).fetchone()
    if not family:
        raise ValueError(f"family_key relazione non trovato: {family_key}")
    family_id = int(family[0])

    variant_key = str(ref.get("variant_key") or "").strip()
    if not variant_key:
        return family_id, None
    variant = con.execute(
        "SELECT id FROM product_variants WHERE family_id=? AND variant_key=?",
        (family_id, variant_key),
    ).fetchone()
    if not variant:
        raise ValueError(
            f"variant_key relazione non trovato: {family_key}/{variant_key}"
        )
    return family_id, int(variant[0])


def upsert_relation(
    con: sqlite3.Connection,
    *,
    subject_family_id: int,
    subject_variant_id: int | None,
    relation_type: str,
    object_family_id: int,
    object_variant_id: int | None,
    source: str,
    confidence: float,
) -> bool:
    ensure_relation_schema(con)
    kind = str(relation_type or "").strip().lower()
    if kind not in RELATION_TYPES:
        raise ValueError(f"relation_type non supportato: {kind or '<vuoto>'}")
    if (subject_family_id, subject_variant_id) == (object_family_id, object_variant_id):
        raise ValueError("una relazione non puo puntare alla stessa entita")
    conf = max(0.0, min(float(confidence), 1.0))
    row = con.execute(
        """
        SELECT id, confidence FROM product_relations
        WHERE subject_family_id IS ? AND subject_variant_id IS ?
          AND relation_type=?
          AND object_family_id IS ? AND object_variant_id IS ?
          AND COALESCE(source, '')=COALESCE(?, '')
        """,
        (
            subject_family_id,
            subject_variant_id,
            kind,
            object_family_id,
            object_variant_id,
            source,
        ),
    ).fetchone()
    stamp = _now()
    if row:
        con.execute(
            "UPDATE product_relations SET confidence=?, updated_at=? WHERE id=?",
            (max(float(row[1] or 0.0), conf), stamp, int(row[0])),
        )
        return False
    con.execute(
        """
        INSERT INTO product_relations(
            subject_family_id, subject_variant_id, relation_type,
            object_family_id, object_variant_id, source, confidence,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            subject_family_id,
            subject_variant_id,
            kind,
            object_family_id,
            object_variant_id,
            source,
            conf,
            stamp,
            stamp,
        ),
    )
    return True


def import_relation(
    con: sqlite3.Connection, item: dict[str, Any], *, source: str
) -> bool:
    subject = item.get("subject")
    obj = item.get("object")
    if not isinstance(subject, dict) or not isinstance(obj, dict):
        raise ValueError("relation richiede subject e object")
    subject_family_id, subject_variant_id = resolve_entity_ref(con, subject)
    object_family_id, object_variant_id = resolve_entity_ref(con, obj)
    return upsert_relation(
        con,
        subject_family_id=subject_family_id,
        subject_variant_id=subject_variant_id,
        relation_type=str(item.get("type") or item.get("relation_type") or ""),
        object_family_id=object_family_id,
        object_variant_id=object_variant_id,
        source=str(item.get("source") or source),
        confidence=float(item.get("confidence", 0.8)),
    )


@dataclass(frozen=True)
class ProductRelation:
    direction: str
    relation_type: str
    family_id: int
    variant_id: int | None
    brand: str
    family_name: str
    variant_name: str
    source: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def relations_for_entity(
    con: sqlite3.Connection,
    family_id: int,
    variant_id: int | None = None,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    ensure_relation_schema(con)
    variant_clause_out = "r.subject_variant_id IS NULL"
    variant_clause_in = "r.object_variant_id IS NULL"
    params_out: list[Any] = [family_id]
    params_in: list[Any] = [family_id]
    if variant_id is not None:
        variant_clause_out = "(r.subject_variant_id IS NULL OR r.subject_variant_id=?)"
        variant_clause_in = "(r.object_variant_id IS NULL OR r.object_variant_id=?)"
        params_out.append(variant_id)
        params_in.append(variant_id)

    def fetch(direction: str, where: str, params: list[Any], other: str) -> list[ProductRelation]:
        rows = con.execute(
            f"""
            SELECT r.relation_type, f.id, v.id, COALESCE(f.brand, ''),
                   f.family_name, COALESCE(v.variant_name, ''),
                   COALESCE(r.source, ''), r.confidence
            FROM product_relations r
            JOIN product_families f ON f.id=r.{other}_family_id
            LEFT JOIN product_variants v
              ON v.id=r.{other}_variant_id AND v.family_id=f.id
            WHERE {where}
            ORDER BY r.confidence DESC, r.id
            LIMIT ?
            """,
            [*params, max(1, int(limit))],
        )
        return [
            ProductRelation(
                direction=direction,
                relation_type=str(row[0]),
                family_id=int(row[1]),
                variant_id=int(row[2]) if row[2] is not None else None,
                brand=str(row[3]),
                family_name=str(row[4]),
                variant_name=str(row[5]),
                source=str(row[6]),
                confidence=round(float(row[7]), 4),
            )
            for row in rows
        ]

    outgoing = fetch(
        "outgoing",
        f"r.subject_family_id=? AND {variant_clause_out}",
        params_out,
        "object",
    )
    incoming = fetch(
        "incoming",
        f"r.object_family_id=? AND {variant_clause_in}",
        params_in,
        "subject",
    )
    combined = sorted(
        [*outgoing, *incoming],
        key=lambda relation: relation.confidence,
        reverse=True,
    )[: max(1, int(limit))]
    return [relation.to_dict() for relation in combined]
