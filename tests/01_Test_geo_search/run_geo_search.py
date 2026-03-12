"""GEO search test.

Runs GEOSearchSkill with a configurable query and prints a summary of results.
When DB_PATH is set, persists series + raw SOFT text to SQLite.

Usage
-----
    uv run python tests/01_Test_geo_search/run_geo_search.py

Environment overrides (all optional):
    DATA_TYPE     default: CITE-seq
    ORGANISM      default: Homo sapiens
    DISEASE       default: (not set)
    TISSUE        default: (not set)
    MAX_RESULTS   default: 35
    SOFT_DIR      directory to save raw Series SOFT files (default: debug_soft/)
                  set to empty string to skip saving
    DB_PATH       SQLite database path (default: data/geo_agent.db)
"""

from __future__ import annotations

import os
import logging
from pathlib import Path

from geo_agent.config import load_config
from geo_agent.models.context import PipelineContext
from geo_agent.models.query import SearchQuery
from geo_agent.ncbi.client import NCBIClient
from geo_agent.skills.search import GEOSearchSkill
from geo_agent.utils.logging import setup_logging

setup_logging(verbose=True)
logger = logging.getLogger(__name__)

DATA_TYPE   = os.getenv("DATA_TYPE",   "CITE-seq")
ORGANISM    = os.getenv("ORGANISM",    "Homo sapiens")
DISEASE     = os.getenv("DISEASE",     "") or None
TISSUE      = os.getenv("TISSUE",      "") or None
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "35"))
SOFT_DIR    = os.getenv("SOFT_DIR", "tests/01_Test_geo_search/debug_soft") or None
DB_PATH     = Path(os.getenv("DB_PATH", "data/geo_agent.db"))


if __name__ == "__main__":
    config = load_config()
    client = NCBIClient(api_key=config.api_key, email=config.email, tool=config.tool_name)

    query = SearchQuery(
        data_type=DATA_TYPE,
        organism=ORGANISM,
        disease=DISEASE,
        tissue=TISSUE,
        max_results=MAX_RESULTS,
    )

    # ── Database setup ────────────────────────────────────────────────────
    from geo_agent.db import Database, DatabaseRepository

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = Database(DB_PATH)
    db.open()
    repo = DatabaseRepository(db)
    run_id = repo.create_run(query)

    print("=" * 70)
    print(f"Query : {query.to_geo_query()}")
    print(f"SOFT  : {SOFT_DIR or '(not saving)'}")
    print(f"DB    : {DB_PATH}  (run_id={run_id})")
    print("=" * 70)

    ctx = PipelineContext(query=query, db=repo, pipeline_run_id=run_id)
    try:
        ctx = GEOSearchSkill(client, debug_dir=SOFT_DIR).execute(ctx)
    finally:
        status = "failed" if ctx.errors else "completed"
        repo.finish_run(run_id, ctx.total_found, status)

    print(f"\nTotal in GEO : {ctx.total_found}")
    print(f"Returned     : {len(ctx.datasets)}\n")

    # ── Per-dataset summary ────────────────────────────────────────────────
    col_w = (12, 200, 16, 6)  # acc, title, organism, n_samples
    header = (
        f"{'Accession':<{col_w[0]}}  "
        f"{'Title':<{col_w[1]}}  "
        f"{'Organism':<{col_w[2]}}  "
        f"{'N':>{col_w[3]}}"
    )
    print(header)
    print("-" * (sum(col_w) + 6))

    for ds in ctx.datasets:
        title = ds.title[:col_w[1]] if ds.title else ""
        org   = ds.organism[:col_w[2]] if ds.organism else ""
        print(
            f"{ds.accession:<{col_w[0]}}  "
            f"{title:<{col_w[1]}}  "
            f"{org:<{col_w[2]}}  "
            f"{ds.sample_count:>{col_w[3]}}"
        )

    # ── Supplementary file types ───────────────────────────────────────────
    ext_counts: dict[str, int] = {}
    for ds in ctx.datasets:
        for sf in ds.supplementary_files:
            ext = Path(sf.name).suffix.lower() if sf.name else "(none)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

    if ext_counts:
        print("\nSupplementary file extensions:")
        for ext, n in sorted(ext_counts.items(), key=lambda x: -x[1]):
            print(f"  {ext:<12} {n}")

    if ctx.errors:
        print(f"\nErrors ({len(ctx.errors)}):")
        for e in ctx.errors:
            print(f"  - {e}")

    # ── Database summary ──────────────────────────────────────────────────
    series_count = db.conn.execute(
        "SELECT COUNT(*) FROM series WHERE pipeline_run_id = ?", (run_id,)
    ).fetchone()[0]
    soft_count = db.conn.execute(
        "SELECT COUNT(*) FROM series_soft_text WHERE pipeline_run_id = ?", (run_id,)
    ).fetchone()[0]
    supp_count = db.conn.execute(
        "SELECT COUNT(*) FROM series_supplementary_file WHERE pipeline_run_id = ?", (run_id,)
    ).fetchone()[0]
    rel_count = db.conn.execute(
        "SELECT COUNT(*) FROM series_relation WHERE pipeline_run_id = ?", (run_id,)
    ).fetchone()[0]

    print(f"\n{'=' * 70}")
    print(f"Database summary (run_id={run_id})")
    print(f"{'=' * 70}")
    print(f"  series                  : {series_count}")
    print(f"  series_soft_text        : {soft_count}")
    print(f"  series_supplementary_file: {supp_count}")
    print(f"  series_relation         : {rel_count}")

    db.close()
    print(f"\n[ok] Database saved to {DB_PATH}")
