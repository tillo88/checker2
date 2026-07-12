#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys


def run_stage(name: str, cmd: list[str]) -> int:
    print("\n" + "=" * 100, flush=True)
    print(f"[stage] {name}", flush=True)
    print("$ " + " ".join(cmd), flush=True)
    print("=" * 100, flush=True)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="", flush=True)
    return int(proc.wait())


def backup_reset_db(db_path: str) -> None:
    db = Path(db_path)
    if not db.exists():
        print(f"[reset] DB non esiste ancora: {db}", flush=True)
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = db.with_name(db.name + f".bak-{stamp}")
    shutil.move(str(db), str(backup))
    print(f"[reset] backup DB: {backup}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full strong marketplace pipeline: fetch -> clean -> verify online -> promote -> status.")
    parser.add_argument("--db", default=os.getenv("SPYENGINE_MARKET_CACHE_DB", "data/marketplace_cache/marketplace.sqlite"))

    parser.add_argument("--sources", default="refurbed", help="comma-separated sources")
    parser.add_argument("--max-depth", type=int, default=1)
    parser.add_argument("--max-categories-per-source", type=int, default=20)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--per-category-limit", type=int, default=40)
    parser.add_argument("--sleep-min", type=float, default=4.0)
    parser.add_argument("--sleep-max", type=float, default=12.0)
    parser.add_argument("--force", action="store_true", help="refetch pages already completed")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-robots", action="store_true")

    parser.add_argument("--limit", type=int, default=500, help="batch size for clean/verify/promote")
    parser.add_argument("--ai-clean", action="store_true", help="use AI during clean stage only on uncertain cases")
    parser.add_argument("--include-rejected-clean", action="store_true", default=True, help="verify online also records rejected by clean stage")
    parser.add_argument("--skip-include-rejected-clean", action="store_true", help="do not verify records rejected by clean stage")
    parser.add_argument("--dry-run", action="store_true", help="crawl dry-run + postprocess dry-run; no promote")
    parser.add_argument("--reset-cache-with-backup", action="store_true", help="backup/reset DB before starting")
    parser.add_argument("--continue-on-error", action="store_true", help="continue later stages even if a stage fails")
    args = parser.parse_args()

    if args.skip_include_rejected_clean:
        args.include_rejected_clean = False

    py = sys.executable
    failures: list[tuple[str, int]] = []

    if args.reset_cache_with_backup:
        backup_reset_db(args.db)

    crawl_cmd = [
        py,
        "scripts/nightly_marketplace_harvester.py",
        "crawl-sites",
        "--sources",
        args.sources,
        "--max-depth",
        str(args.max_depth),
        "--max-categories-per-source",
        str(args.max_categories_per_source),
        "--max-pages",
        str(args.max_pages),
        "--per-category-limit",
        str(args.per_category_limit),
        "--sleep-min",
        str(args.sleep_min),
        "--sleep-max",
        str(args.sleep_max),
    ]
    if args.force:
        crawl_cmd.append("--force")
    if args.verbose:
        crawl_cmd.append("--verbose")
    if args.no_robots:
        crawl_cmd.append("--no-robots")
    if args.dry_run:
        crawl_cmd.append("--dry-run")

    rc = run_stage("1/5 FETCH crawl-sites", crawl_cmd)
    if rc:
        failures.append(("fetch", rc))
        if not args.continue_on_error:
            print(f"[abort] fetch failed rc={rc}", flush=True)
            return rc

    post_cmd = [
        py,
        "scripts/marketplace_postprocess_pipeline.py",
        "--db",
        args.db,
        "--limit",
        str(args.limit),
    ]
    if args.ai_clean:
        post_cmd.append("--ai-clean")
    if args.include_rejected_clean:
        post_cmd.append("--include-rejected-clean")
    if args.dry_run:
        post_cmd.append("--dry-run")

    rc = run_stage("2-5/5 CLEAN -> VERIFY ONLINE -> PROMOTE -> STATUS", post_cmd)
    if rc:
        failures.append(("postprocess", rc))
        if not args.continue_on_error:
            print(f"[abort] postprocess failed rc={rc}", flush=True)
            return rc

    status_cmd = [py, "scripts/marketplace_pipeline_status.py", "--db", args.db, "--recent", "10"]
    rc = run_stage("FINAL STATUS", status_cmd)
    if rc:
        failures.append(("status", rc))

    if failures:
        print(f"[done-with-errors] {failures}", flush=True)
        return 1

    print("[done] all-in-one pipeline completed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
