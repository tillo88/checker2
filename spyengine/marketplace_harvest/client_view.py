from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from .opportunity_scoring import score_opportunity_rows



def connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).resolve()
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    )


def _joins(con: sqlite3.Connection) -> list[str]:
    joins: list[str] = []
    joins.append(
        "LEFT JOIN listing_detail_reviews dr ON dr.listing_id = l.id"
        if table_exists(con, "listing_detail_reviews")
        else "LEFT JOIN (SELECT NULL listing_id, NULL description_sample) dr ON 1=0"
    )
    joins.append(
        "LEFT JOIN listing_cleaning_reviews cr ON cr.listing_id = l.id"
        if table_exists(con, "listing_cleaning_reviews")
        else "LEFT JOIN (SELECT NULL listing_id, NULL decision, NULL confidence, "
        "NULL normalized_title, NULL normalized_category, NULL reason) cr ON 1=0"
    )
    joins.append(
        "LEFT JOIN listing_online_verifications ov ON ov.listing_id = l.id"
        if table_exists(con, "listing_online_verifications")
        else "LEFT JOIN (SELECT NULL listing_id, NULL status, NULL confidence, NULL reason) ov ON 1=0"
    )
    joins.append(
        "LEFT JOIN listing_online_product_research r ON r.listing_id = l.id"
        if table_exists(con, "listing_online_product_research")
        else "LEFT JOIN (SELECT NULL listing_id, NULL canonical_category, NULL canonical_title, "
        "NULL canonical_brand, NULL canonical_model, NULL confidence) r ON 1=0"
    )
    joins.append(
        "LEFT JOIN listing_ai_edge_reviews ar ON ar.listing_id = l.id"
        if table_exists(con, "listing_ai_edge_reviews")
        else "LEFT JOIN (SELECT NULL listing_id, NULL status, NULL canonical_category, "
        "NULL canonical_title, NULL confidence) ar ON 1=0"
    )
    return joins


# Cleaning is the final pipeline handoff and is therefore authoritative.
# AI Edge is useful only when it actually resolved a non-empty value.
RESOLVED_TITLE_SQL = """
COALESCE(
    NULLIF(TRIM(cr.normalized_title), ''),
    CASE WHEN ar.status = 'resolved' THEN NULLIF(TRIM(ar.canonical_title), '') END,
    NULLIF(TRIM(r.canonical_title), ''),
    l.title
)
""".strip()

RESOLVED_CATEGORY_SQL = """
COALESCE(
    NULLIF(NULLIF(TRIM(cr.normalized_category), ''), 'unknown'),
    CASE WHEN ar.status = 'resolved'
         THEN NULLIF(NULLIF(TRIM(ar.canonical_category), ''), 'unknown') END,
    NULLIF(NULLIF(TRIM(r.canonical_category), ''), 'unknown'),
    NULLIF(NULLIF(TRIM(l.category), ''), 'unknown'),
    'unknown'
)
""".strip()


def query_client_listings(
    con: sqlite3.Connection,
    *,
    search: str = "",
    category: str = "",
    source: str = "",
    status: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
    limit: int = 150,
    include_unknown: bool = False,
    opportunity_safe: bool = False,
) -> list[dict[str, Any]]:
    if not table_exists(con, "listings"):
        return []

    requested_limit = max(1, min(int(limit), 5000))
    where: list[str] = []
    params: list[Any] = []

    if opportunity_safe:
        where.extend(
            [
                "ov.status = 'verified'",
                "cr.decision = 'accept'",
                "l.price IS NOT NULL AND l.price > 0",
                "LOWER(COALESCE(l.url, '')) LIKE 'http%'",
                f"({RESOLVED_CATEGORY_SQL}) <> 'unknown'",
            ]
        )
    else:
        if status:
            where.append("ov.status = ?")
            params.append(status)
        if not include_unknown:
            where.append(f"({RESOLVED_CATEGORY_SQL}) <> 'unknown'")

    term = search.strip().lower()
    if term:
        where.append(
            f"(LOWER(l.title) LIKE ? OR LOWER({RESOLVED_TITLE_SQL}) LIKE ? "
            "OR LOWER(COALESCE(dr.description_sample, '')) LIKE ? OR LOWER(COALESCE(l.seller, '')) LIKE ?)"
        )
        q = f"%{term}%"
        params.extend([q, q, q, q])
    if category:
        where.append(f"({RESOLVED_CATEGORY_SQL}) = ?")
        params.append(category)
    if source:
        where.append("l.source = ?")
        params.append(source)
    if min_price is not None and float(min_price) > 0:
        where.append("l.price >= ?")
        params.append(float(min_price))
    if max_price is not None and float(max_price) > 0:
        where.append("l.price <= ?")
        params.append(float(max_price))

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    sql = f"""
        SELECT
            l.id,
            l.source,
            l.title AS original_title,
            {RESOLVED_TITLE_SQL} AS title,
            {RESOLVED_CATEGORY_SQL} AS category,
            COALESCE(NULLIF(TRIM(r.canonical_brand), ''), '') AS brand,
            COALESCE(NULLIF(TRIM(r.canonical_model), ''), '') AS model,
            l.price,
            l.currency,
            l.location,
            l.seller,
            l.url,
            ov.status AS verify_status,
            cr.decision AS clean_decision,
            COALESCE(cr.confidence, ar.confidence, r.confidence, ov.confidence, 0.0) AS confidence,
            COALESCE(cr.reason, ov.reason, '') AS reason,
            l.last_seen
        FROM listings l
        {' '.join(_joins(con))}
        {where_sql}
        ORDER BY
            CASE COALESCE(ov.status, '')
                WHEN 'verified' THEN 0
                WHEN 'verified_conflict' THEN 1
                WHEN 'uncertain' THEN 2
                ELSE 3
            END,
            COALESCE(cr.confidence, ar.confidence, r.confidence, ov.confidence, 0.0) DESC,
            COALESCE(l.last_seen, l.first_seen, '') DESC
        LIMIT ?
    """
    params.append(5000 if opportunity_safe else requested_limit)
    rows = [dict(row) for row in con.execute(sql, params)]
    if opportunity_safe:
        return score_opportunity_rows(rows)[:requested_limit]
    return rows


def load_client_listings(
    db_path: str | Path,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    con = connect_readonly(db_path)
    try:
        return query_client_listings(con, **kwargs)
    finally:
        con.close()
