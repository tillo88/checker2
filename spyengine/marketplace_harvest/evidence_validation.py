from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from spyengine.marketplace_harvest.product_knowledge import utc_now


GTIN_RE = re.compile(r"\b(UPC|EAN|GTIN)(?:-\d+)?\s*[:#-]?\s*(\d{8}|\d{12,14})\b", re.I)


def valid_gtin(value: str) -> bool:
    digits = str(value or "").strip()
    if len(digits) not in {8, 12, 13, 14} or not digits.isdigit():
        return False
    data = [int(ch) for ch in digits[:-1]]
    check = int(digits[-1])
    total = 0
    for idx, number in enumerate(reversed(data), start=1):
        total += number * (3 if idx % 2 == 1 else 1)
    return (10 - total % 10) % 10 == check


def identifier_type(label: str, value: str) -> str:
    label = label.lower()
    if label == "upc" or len(value) == 12:
        return "upc"
    if label == "ean" or len(value) in {8, 13}:
        return "ean"
    return "gtin"


def ensure_proposal_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS catalog_fact_proposals (
            id INTEGER PRIMARY KEY,
            family_id INTEGER,
            variant_id INTEGER,
            proposal_type TEXT NOT NULL,
            field_name TEXT NOT NULL,
            value_json TEXT NOT NULL,
            support_count INTEGER NOT NULL,
            sources_json TEXT NOT NULL,
            evidence_ids_json TEXT NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(family_id, variant_id, proposal_type, field_name, value_json)
        );
        CREATE INDEX IF NOT EXISTS idx_catalog_fact_proposals_status
            ON catalog_fact_proposals(status, proposal_type, confidence);
        """
    )
    con.commit()


@dataclass
class FactProposal:
    family_id: int | None
    variant_id: int | None
    proposal_type: str
    field_name: str
    value: Any
    support_count: int
    sources: list[str]
    evidence_ids: list[int]
    confidence: float
    status: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "variant_id": self.variant_id,
            "proposal_type": self.proposal_type,
            "field_name": self.field_name,
            "value": self.value,
            "support_count": self.support_count,
            "sources": self.sources,
            "evidence_ids": self.evidence_ids,
            "confidence": self.confidence,
            "status": self.status,
            "reason": self.reason,
        }


def extract_identifier_proposals(con: sqlite3.Connection) -> list[FactProposal]:
    groups: dict[tuple[int | None, int | None, str, str], dict[str, Any]] = defaultdict(
        lambda: {"sources": set(), "evidence_ids": []}
    )
    for row in con.execute(
        """
        SELECT id, family_id, variant_id, source_ref, excerpt, value_json
        FROM product_evidence
        WHERE evidence_type='web_discovery' AND field_name='identifiers'
        """
    ):
        text = f"{row[4] or ''} {row[5] or ''}"
        host = urlparse(str(row[3] or "")).netloc.lower().removeprefix("www.")
        for match in GTIN_RE.finditer(text):
            value = match.group(2)
            if not valid_gtin(value):
                continue
            kind = identifier_type(match.group(1), value)
            key = (
                int(row[1]) if row[1] is not None else None,
                int(row[2]) if row[2] is not None else None,
                kind,
                value,
            )
            if host:
                groups[key]["sources"].add(host)
            groups[key]["evidence_ids"].append(int(row[0]))

    proposals: list[FactProposal] = []
    for (family_id, variant_id, kind, value), data in groups.items():
        sources = sorted(data["sources"])
        support = len(sources)
        if support >= 3:
            conf, status, reason = 0.96, "promotable", "consenso_fra_almeno_tre_domini"
        elif support == 2:
            conf, status, reason = 0.88, "promotable", "consenso_fra_due_domini"
        else:
            conf, status, reason = 0.55, "needs_evidence", "una_sola_fonte_indipendente"
        proposals.append(
            FactProposal(
                family_id,
                variant_id,
                "identifier",
                kind,
                value,
                support,
                sources,
                sorted(set(data["evidence_ids"])),
                conf,
                status,
                reason,
            )
        )
    return sorted(proposals, key=lambda item: (item.confidence, item.support_count), reverse=True)


def persist_proposals(con: sqlite3.Connection, proposals: list[FactProposal]) -> int:
    ensure_proposal_schema(con)
    stamp = utc_now()
    changed = 0
    for proposal in proposals:
        cur = con.execute(
            """
            INSERT INTO catalog_fact_proposals(
                family_id, variant_id, proposal_type, field_name, value_json,
                support_count, sources_json, evidence_ids_json, confidence,
                status, reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(family_id, variant_id, proposal_type, field_name, value_json)
            DO UPDATE SET
                support_count=excluded.support_count,
                sources_json=excluded.sources_json,
                evidence_ids_json=excluded.evidence_ids_json,
                confidence=excluded.confidence,
                status=excluded.status,
                reason=excluded.reason,
                updated_at=excluded.updated_at
            """,
            (
                proposal.family_id,
                proposal.variant_id,
                proposal.proposal_type,
                proposal.field_name,
                json.dumps(proposal.value, ensure_ascii=False, sort_keys=True),
                proposal.support_count,
                json.dumps(proposal.sources, ensure_ascii=False),
                json.dumps(proposal.evidence_ids),
                proposal.confidence,
                proposal.status,
                proposal.reason,
                stamp,
                stamp,
            ),
        )
        changed += int(cur.rowcount > 0)
    con.commit()
    return changed


def promote_identifier_proposals(con: sqlite3.Connection, *, min_confidence: float = 0.88) -> int:
    ensure_proposal_schema(con)
    stamp = utc_now()
    promoted = 0
    rows = list(
        con.execute(
            """
            SELECT id, family_id, variant_id, field_name, value_json, confidence, sources_json
            FROM catalog_fact_proposals
            WHERE proposal_type='identifier' AND status='promotable' AND confidence>=?
            """,
            (float(min_confidence),),
        )
    )
    for row in rows:
        value = str(json.loads(str(row[4])))
        exists = con.execute(
            """
            SELECT 1 FROM product_identifiers
            WHERE family_id IS ? AND variant_id IS ?
              AND identifier_type=? AND identifier_value=?
            """,
            (row[1], row[2], row[3], value),
        ).fetchone()
        if not exists:
            con.execute(
                """
                INSERT INTO product_identifiers(
                    family_id, variant_id, identifier_type, identifier_value,
                    source, confidence, first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (row[1], row[2], row[3], value, "multi_source_web_evidence", float(row[5]), stamp, stamp),
            )
            promoted += 1
        con.execute(
            "UPDATE catalog_fact_proposals SET status='promoted', updated_at=? WHERE id=?",
            (stamp, int(row[0])),
        )
    con.commit()
    return promoted
