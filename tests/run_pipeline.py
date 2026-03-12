#!/usr/bin/env python3
"""Run the full GEO Agent pipeline (steps 01–05) sequentially.

Each step depends on the prior. Stops immediately on failure.
All steps share the same database at data/geo_agent.db.

Usage
-----
    uv run python tests/run_pipeline.py              # run all steps
    uv run python tests/run_pipeline.py --from 3      # start from step 03
    uv run python tests/run_pipeline.py --steps 1,2,4 # run only specific steps
    uv run python tests/run_pipeline.py --dry-run      # show what would run

Environment overrides (all optional):
    DB_PATH         SQLite database path (default: data/geo_agent.db)
    + all env vars from individual test scripts
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

STEPS = [
    (1, "01_Test_geo_search",          "run_geo_search.py",              "GEO Search → save series + SOFT to DB"),
    (2, "02_Test_hierarchy",           "run_hierarchy.py",               "Hierarchy classification → update DB"),
    (3, "03_Test_fetch_family_soft",   "run_fetch_family_soft.py",       "Fetch Family SOFT → save to disk"),
    (4, "04_Test_family_soft_parse",   "run_family_soft_parser_debug.py","Parse Family SOFT → save samples to DB"),
    (5, "05_Test_multiomics_analysis", "run_multiomics_analysis_series.py", "LLM annotation → save annotations to DB"),
]

TESTS_DIR = Path(__file__).resolve().parent


def run_step(num: int, dirname: str, script: str, desc: str, db_path: str) -> bool:
    """Run one pipeline step. Returns True on success."""
    script_path = TESTS_DIR / dirname / script
    if not script_path.exists():
        print(f"  [ERROR] Script not found: {script_path}")
        return False

    env = {**os.environ, "DB_PATH": db_path}
    result = subprocess.run(
        [sys.executable, str(script_path)],
        env=env,
        cwd=str(TESTS_DIR.parent),  # project root
    )
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full GEO Agent pipeline")
    parser.add_argument(
        "--from", dest="from_step", type=int, default=1,
        help="Start from step N (default: 1)",
    )
    parser.add_argument(
        "--steps", type=str, default=None,
        help="Comma-separated step numbers to run, e.g. '1,2,4'",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would run without executing",
    )
    parser.add_argument(
        "--db", type=str, default=None,
        help="SQLite database path (default: data/geo_agent.db)",
    )
    args = parser.parse_args()

    db_path = args.db or os.getenv("DB_PATH", "data/geo_agent.db")

    # Determine which steps to run
    if args.steps:
        selected = {int(s.strip()) for s in args.steps.split(",")}
        steps = [(n, d, s, desc) for n, d, s, desc in STEPS if n in selected]
    else:
        steps = [(n, d, s, desc) for n, d, s, desc in STEPS if n >= args.from_step]

    if not steps:
        print("No steps selected.")
        sys.exit(1)

    # Header
    print("=" * 70)
    print("GEO Agent Pipeline")
    print("=" * 70)
    print(f"  DB     : {db_path}")
    print(f"  Steps  : {', '.join(f'{n:02d}' for n, *_ in steps)}")
    print("=" * 70)

    if args.dry_run:
        for num, dirname, script, desc in steps:
            print(f"  [{num:02d}] {desc}")
            print(f"       → tests/{dirname}/{script}")
        print("\n(dry-run, nothing executed)")
        return

    results: list[tuple[int, str, bool, float]] = []
    pipeline_start = time.time()

    for num, dirname, script, desc in steps:
        print(f"\n{'=' * 70}")
        print(f"  Step {num:02d}: {desc}")
        print(f"  Script: tests/{dirname}/{script}")
        print(f"{'=' * 70}\n")

        step_start = time.time()
        ok = run_step(num, dirname, script, desc, db_path)
        elapsed = time.time() - step_start
        results.append((num, desc, ok, elapsed))

        if not ok:
            print(f"\n[FAIL] Step {num:02d} failed after {elapsed:.1f}s — pipeline aborted.")
            break

    # Summary
    total_elapsed = time.time() - pipeline_start
    print(f"\n{'=' * 70}")
    print("Pipeline Summary")
    print(f"{'=' * 70}")
    for num, desc, ok, elapsed in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] Step {num:02d}: {desc} ({elapsed:.1f}s)")

    passed = sum(1 for *_, ok, _ in results if ok)
    failed = len(results) - passed
    print(f"\n  Total: {passed} passed, {failed} failed, {total_elapsed:.1f}s elapsed")
    print(f"  DB   : {db_path}")

    if failed:
        sys.exit(1)
    else:
        print(f"\n  All steps completed successfully!")


if __name__ == "__main__":
    main()
