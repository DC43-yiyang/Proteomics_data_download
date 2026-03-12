"""Run Family SOFT structuring and output structured JSON.

Reads Family SOFT files from SOFT_DIR (populated by run_fetch_family_soft.py),
parses each series with FamilySoftStructurerSkill, and writes a single
structured JSON to OUTPUT_DIR. When DB_PATH is set, also persists parsed
samples to the database.

No NCBI requests are made. Run the fetch test first to populate SOFT_DIR:
    uv run python tests/03_Test_fetch_family_soft/run_fetch_family_soft.py

Usage
-----
    uv run python tests/04_Test_family_soft_parse/run_family_soft_parser_debug.py
    uv run python tests/04_Test_family_soft_parse/run_family_soft_parser_debug.py --series-id GSE266455

Environment overrides (all optional):
    SOFT_DIR    directory containing *_family.soft files
                (default: tests/03_Test_fetch_family_soft/debug_family_soft)
    OUTPUT_DIR  directory to write structured JSON
                (default: tests/04_Test_family_soft_parse/debug_family_soft_parse)
    DB_PATH     SQLite database path (default: data/geo_agent.db)

Output
------
    {OUTPUT_DIR}/family_soft_structured.json
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geo_agent.skills.family_soft_structurer import structure_family_soft_text

HERE = Path(__file__).resolve().parent

SOFT_DIR   = Path(os.getenv("SOFT_DIR",   HERE.parent / "03_Test_fetch_family_soft" / "debug_family_soft"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", HERE / "debug_family_soft_parse"))
DB_PATH    = Path(os.getenv("DB_PATH", "data/geo_agent.db"))


def _scan_series_from_soft_dir(soft_dir: Path) -> list[str]:
    return sorted(path.stem.replace("_family", "") for path in soft_dir.glob("*_family.soft"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--series-id",
        action="append",
        default=[],
        help="Run only specific GSE accession(s), e.g. --series-id GSE269123",
    )
    args = parser.parse_args()

    if not SOFT_DIR.exists():
        raise SystemExit(
            f"SOFT_DIR not found: {SOFT_DIR}\n"
            "Run fetch test first:\n"
            "  uv run python tests/03_Test_fetch_family_soft/run_fetch_family_soft.py"
        )

    discovered = _scan_series_from_soft_dir(SOFT_DIR)
    if not discovered:
        raise SystemExit(f"No *_family.soft files found in {SOFT_DIR}")

    if args.series_id:
        want = {s.strip() for s in args.series_id if s.strip()}
        series_ids = [sid for sid in discovered if sid in want]
        missing = want - set(series_ids)
        if missing:
            print(f"[warn] not found in SOFT_DIR: {sorted(missing)}", flush=True)
    else:
        series_ids = discovered

    if not series_ids:
        raise SystemExit("No series IDs to process.")

    # ── Database setup ────────────────────────────────────────────────────
    from geo_agent.db import Database, DatabaseRepository

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = Database(DB_PATH)
    db.open()
    repo = DatabaseRepository(db)

    run_id = repo.get_latest_run_id()
    if run_id is None:
        # No previous run exists — create a placeholder
        from geo_agent.models.query import SearchQuery
        run_id = repo.create_run(SearchQuery(data_type="(local)"))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "family_soft_structured.json"

    print(f"[run] series_count={len(series_ids)}  soft_dir={SOFT_DIR}", flush=True)
    print(f"[db]  {DB_PATH}  (run_id={run_id})", flush=True)

    structured: dict[str, dict[str, Any]] = {}
    total_samples_saved = 0

    for idx, series_id in enumerate(series_ids, start=1):
        soft_path = SOFT_DIR / f"{series_id}_family.soft"
        if not soft_path.exists():
            print(f"[{idx}/{len(series_ids)}] SKIP {series_id} — file not found", flush=True)
            continue

        print(f"[{idx}/{len(series_ids)}] parsing {series_id}", flush=True)
        series_data = structure_family_soft_text(
            series_id=series_id,
            soft_text=soft_path.read_text(errors="ignore"),
            source_file=str(soft_path),
        )
        structured[series_id] = series_data

        sample_count = series_data.get("sample_count", 0)
        print(
            f"[{idx}/{len(series_ids)}] done {series_id}  "
            f"samples={sample_count}",
            flush=True,
        )

        # Persist to DB
        samples = series_data.get("samples", [])
        # Ensure the series exists in DB (it may not if step 01 wasn't run for this series)
        db.conn.execute(
            """INSERT OR IGNORE INTO series
               (accession, pipeline_run_id, uid, title, in_search_results)
               VALUES (?,?,'','',1)""",
            (series_id, run_id),
        )
        db.conn.commit()
        repo.save_samples_batch(series_id, run_id, samples)
        total_samples_saved += len(samples)

        series_supp = series_data.get("series_supplementary_files", [])
        if series_supp:
            repo.replace_series_supplementary_files(series_id, run_id, series_supp)
            print(f"  → {len(series_supp)} series supplementary file(s) saved", flush=True)

    # Write JSON output
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "series_count": len(structured),
        "series_ids": list(structured.keys()),
        "series_results": structured,
    }
    output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwritten: {output_file}")

    # ── Database summary ──────────────────────────────────────────────────
    sample_count = db.conn.execute(
        "SELECT COUNT(*) FROM sample WHERE pipeline_run_id = ?", (run_id,)
    ).fetchone()[0]
    char_count = db.conn.execute(
        "SELECT COUNT(*) FROM sample_characteristic WHERE pipeline_run_id = ?", (run_id,)
    ).fetchone()[0]
    sup_count = db.conn.execute(
        "SELECT COUNT(*) FROM sample_supplementary_file WHERE pipeline_run_id = ?", (run_id,)
    ).fetchone()[0]
    rel_count = db.conn.execute(
        "SELECT COUNT(*) FROM sample_relation WHERE pipeline_run_id = ?", (run_id,)
    ).fetchone()[0]

    print(f"\n{'=' * 70}")
    print(f"Database summary (run_id={run_id})")
    print(f"{'=' * 70}")
    print(f"  samples saved this run    : {total_samples_saved}")
    print(f"  sample (total)            : {sample_count}")
    print(f"  sample_characteristic     : {char_count}")
    print(f"  sample_supplementary_file : {sup_count}")
    print(f"  sample_relation           : {rel_count}")

    db.close()
    print(f"\n[ok] Samples persisted to {DB_PATH}")


if __name__ == "__main__":
    main()
