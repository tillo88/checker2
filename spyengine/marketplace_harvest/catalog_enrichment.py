from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


TASK_TYPES = ("identifiers", "specifications", "variants", "aliases")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or now_utc()).isoformat(timespec="seconds")


def ensure_enrichment_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS catalog_sources (
            id INTEGER PRIMARY KEY,
            source_key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            base_url TEXT,
            reliability REAL NOT NULL DEFAULT 0.5,
            enabled INTEGER NOT NULL DEFAULT 1,
            policy_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS catalog_enrichment_tasks (
            id INTEGER PRIMARY KEY,
            family_id INTEGER NOT NULL,
            variant_id INTEGER,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            priority INTEGER NOT NULL DEFAULT 100,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 5,
            lease_until TEXT,
            worker_id TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(family_id, variant_id, task_type),
            FOREIGN KEY(family_id) REFERENCES product_families(id),
            FOREIGN KEY(variant_id) REFERENCES product_variants(id)
        );

        CREATE TABLE IF NOT EXISTS catalog_enrichment_runs (
            id INTEGER PRIMARY KEY,
            run_id TEXT NOT NULL UNIQUE,
            worker_id TEXT,
            status TEXT NOT NULL,
            settings_json TEXT NOT NULL DEFAULT '{}',
            stats_json TEXT NOT NULL DEFAULT '{}',
            started_at TEXT NOT NULL,
            finished_at TEXT,
            last_heartbeat_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_catalog_enrichment_pending
            ON catalog_enrichment_tasks(status, priority, id);
        CREATE INDEX IF NOT EXISTS idx_catalog_enrichment_lease
            ON catalog_enrichment_tasks(status, lease_until);
        CREATE INDEX IF NOT EXISTS idx_catalog_enrichment_family
            ON catalog_enrichment_tasks(family_id, variant_id, task_type);
        """
    )
    con.commit()


def _missing(con: sqlite3.Connection, family_id: int, table: str) -> bool:
    if table == "variants":
        sql = "SELECT 1 FROM product_variants WHERE family_id=? LIMIT 1"
        return con.execute(sql, (family_id,)).fetchone() is None
    if table == "aliases":
        sql = """
            SELECT 1 FROM product_aliases
            WHERE family_id=? OR variant_id IN (SELECT id FROM product_variants WHERE family_id=?)
            LIMIT 1
        """
        return con.execute(sql, (family_id, family_id)).fetchone() is None
    if table == "identifiers":
        sql = """
            SELECT 1 FROM product_identifiers
            WHERE family_id=? OR variant_id IN (SELECT id FROM product_variants WHERE family_id=?)
            LIMIT 1
        """
        return con.execute(sql, (family_id, family_id)).fetchone() is None
    if table == "specifications":
        sql = """
            SELECT 1 FROM spec_facts
            WHERE family_id=? OR variant_id IN (SELECT id FROM product_variants WHERE family_id=?)
            LIMIT 1
        """
        return con.execute(sql, (family_id, family_id)).fetchone() is None
    raise ValueError(f"task type non supportato: {table}")


def seed_gap_tasks(con: sqlite3.Connection, limit: int = 100000) -> dict[str, int]:
    ensure_enrichment_schema(con)
    inserted = {task: 0 for task in TASK_TYPES}
    families = list(
        con.execute(
            """
            SELECT id, category, COALESCE(brand, ''), family_name, confidence
            FROM product_families
            ORDER BY confidence DESC, id
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
    )
    now = iso()
    priority_by_type = {
        "identifiers": 10,
        "specifications": 30,
        "variants": 40,
        "aliases": 50,
    }
    for row in families:
        family_id = int(row[0])
        payload = json.dumps(
            {
                "category": str(row[1]),
                "brand": str(row[2]),
                "family_name": str(row[3]),
                "family_confidence": float(row[4] or 0.5),
            },
            ensure_ascii=False,
        )
        for task_type in TASK_TYPES:
            if not _missing(con, family_id, task_type):
                continue
            existing = con.execute(
                "SELECT 1 FROM catalog_enrichment_tasks "
                "WHERE family_id=? AND variant_id IS NULL AND task_type=? LIMIT 1",
                (family_id, task_type),
            ).fetchone()
            if existing:
                continue
            cur = con.execute(
                """
                INSERT OR IGNORE INTO catalog_enrichment_tasks(
                    family_id, variant_id, task_type, status, priority,
                    payload_json, created_at, updated_at
                ) VALUES (?, NULL, ?, 'pending', ?, ?, ?, ?)
                """,
                (family_id, task_type, priority_by_type[task_type], payload, now, now),
            )
            inserted[task_type] += int(cur.rowcount > 0)
    con.commit()
    return inserted


@dataclass
class EnrichmentTask:
    id: int
    family_id: int
    variant_id: int | None
    task_type: str
    priority: int
    attempts: int
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def release_stale_leases(con: sqlite3.Connection) -> int:
    ensure_enrichment_schema(con)
    cur = con.execute(
        """
        UPDATE catalog_enrichment_tasks
        SET status='pending', lease_until=NULL, worker_id=NULL, updated_at=?
        WHERE status='running' AND lease_until IS NOT NULL AND lease_until < ?
        """,
        (iso(), iso()),
    )
    con.commit()
    return int(cur.rowcount)


def claim_task(
    con: sqlite3.Connection,
    worker_id: str,
    *,
    task_types: list[str] | None = None,
    lease_minutes: int = 30,
) -> EnrichmentTask | None:
    ensure_enrichment_schema(con)
    release_stale_leases(con)
    allowed = [task for task in (task_types or TASK_TYPES) if task in TASK_TYPES]
    if not allowed:
        return None
    placeholders = ",".join("?" for _ in allowed)
    con.execute("BEGIN IMMEDIATE")
    try:
        row = con.execute(
            f"""
            SELECT id, family_id, variant_id, task_type, priority, attempts, payload_json
            FROM catalog_enrichment_tasks
            WHERE status='pending' AND attempts < max_attempts
              AND task_type IN ({placeholders})
            ORDER BY priority ASC, id ASC
            LIMIT 1
            """,
            allowed,
        ).fetchone()
        if not row:
            con.commit()
            return None
        lease_until = iso(now_utc() + timedelta(minutes=max(1, lease_minutes)))
        con.execute(
            """
            UPDATE catalog_enrichment_tasks
            SET status='running', attempts=attempts+1, worker_id=?, lease_until=?, updated_at=?
            WHERE id=? AND status='pending'
            """,
            (worker_id, lease_until, iso(), int(row[0])),
        )
        con.commit()
        return EnrichmentTask(
            id=int(row[0]),
            family_id=int(row[1]),
            variant_id=int(row[2]) if row[2] is not None else None,
            task_type=str(row[3]),
            priority=int(row[4]),
            attempts=int(row[5]) + 1,
            payload=json.loads(str(row[6] or "{}")),
        )
    except Exception:
        con.rollback()
        raise


def finish_task(con: sqlite3.Connection, task_id: int, result: dict[str, Any], *, status: str = "completed") -> None:
    if status not in {"completed", "evidence_collected", "needs_review"}:
        raise ValueError(f"stato finale non valido: {status}")
    con.execute(
        """
        UPDATE catalog_enrichment_tasks
        SET status=?, result_json=?, last_error=NULL,
            lease_until=NULL, worker_id=NULL, updated_at=?
        WHERE id=?
        """,
        (status, json.dumps(result, ensure_ascii=False), iso(), int(task_id)),
    )
    con.commit()


def fail_task(con: sqlite3.Connection, task_id: int, error: str, *, retry: bool = True) -> None:
    status = "pending" if retry else "failed"
    con.execute(
        """
        UPDATE catalog_enrichment_tasks
        SET status=?, last_error=?, lease_until=NULL, worker_id=NULL, updated_at=?
        WHERE id=?
        """,
        (status, str(error)[:2000], iso(), int(task_id)),
    )
    con.commit()


def queue_status(con: sqlite3.Connection) -> dict[str, Any]:
    ensure_enrichment_schema(con)
    by_status = {
        str(row[0]): int(row[1])
        for row in con.execute(
            "SELECT status, COUNT(*) FROM catalog_enrichment_tasks GROUP BY status"
        )
    }
    by_type = {
        str(row[0]): {str(row[1]): int(row[2]) for row in con.execute(
            "SELECT task_type, status, COUNT(*) FROM catalog_enrichment_tasks WHERE task_type=? GROUP BY task_type, status",
            (row[0],),
        )}
        for row in con.execute("SELECT DISTINCT task_type FROM catalog_enrichment_tasks")
    }
    claimable = int(con.execute(
        "SELECT COUNT(*) FROM catalog_enrichment_tasks "
        "WHERE status='pending' AND attempts < max_attempts"
    ).fetchone()[0])
    return {
        "total": sum(by_status.values()),
        "claimable": claimable,
        "by_status": by_status,
        "by_type": by_type,
    }
