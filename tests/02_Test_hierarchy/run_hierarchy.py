"""HierarchySkill test — reads from database or local Series SOFT files.

When DB_PATH exists and contains data from a previous search run, reads series
data from the database. Otherwise falls back to loading from local SOFT files
and inserts them into the database first so that hierarchy updates can persist.

No NCBI requests are made. Run the GEO search test first:
    uv run python tests/01_Test_geo_search/run_geo_search.py

Usage
-----
    uv run python tests/02_Test_hierarchy/run_hierarchy.py

Environment overrides (all optional):
    SOFT_DIR        directory containing *.soft files (default: tests/01_Test_geo_search/debug_soft/)
    FAMILIES_FILE   path to save family tree JSON (default: tests/02_Test_hierarchy/hierarchy_families.json)
    STANDALONE_FILE path to save standalone list JSON (default: tests/02_Test_hierarchy/hierarchy_standalone.json)
    DB_PATH         SQLite database path (default: data/geo_agent.db)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from geo_agent.models.context import PipelineContext
from geo_agent.models.dataset import GEODataset
from geo_agent.models.query import SearchQuery
from geo_agent.ncbi.parsers import parse_soft_text
from geo_agent.skills.hierarchy import HierarchySkill
from geo_agent.utils.hierarchy import format_series_hierarchy
from geo_agent.utils.logging import setup_logging

setup_logging(verbose=True)
logger = logging.getLogger(__name__)

SOFT_DIR        = Path(os.getenv("SOFT_DIR",        "tests/01_Test_geo_search/debug_soft"))
FAMILIES_FILE   = os.getenv("FAMILIES_FILE",   "tests/02_Test_hierarchy/hierarchy_families.json") or None
STANDALONE_FILE = os.getenv("STANDALONE_FILE", "tests/02_Test_hierarchy/hierarchy_standalone.json") or None
DB_PATH         = Path(os.getenv("DB_PATH", "data/geo_agent.db"))


def load_datasets_from_soft_dir(soft_dir: Path) -> list[GEODataset]:
    """Reconstruct GEODataset objects from saved Series SOFT files."""
    soft_files = sorted(soft_dir.glob("*.soft"))
    if not soft_files:
        return []

    datasets: list[GEODataset] = []
    for path in soft_files:
        text = path.read_text(encoding="utf-8")
        parsed = parse_soft_text(text)

        accession = parsed.get("accession") or path.stem
        title = parsed.get("title", "")
        relations_raw = parsed.get("relations", "")
        relations = [r.strip() for r in relations_raw.split("; ") if r.strip()]
        sample_ids_raw = parsed.get("sample_ids", "")
        sample_count = len([s for s in sample_ids_raw.split("; ") if s.strip()])

        datasets.append(GEODataset(
            accession=accession,
            uid=accession,
            title=title,
            relations=relations,
            sample_count=sample_count,
        ))

    return datasets


def load_datasets_from_db(db_path: Path) -> tuple[list[GEODataset], int]:
    """Load datasets from the database (latest pipeline run).

    Returns (datasets, run_id).
    """
    from geo_agent.db import Database, DatabaseRepository

    db = Database(db_path)
    db.open()
    repo = DatabaseRepository(db)

    run_id = repo.get_latest_run_id()
    if run_id is None:
        db.close()
        return [], 0

    series_rows = repo.get_series_for_run(run_id)
    datasets: list[GEODataset] = []
    for row in series_rows:
        relations = repo.get_series_relations(row["accession"], run_id)

        datasets.append(GEODataset(
            accession=row["accession"],
            uid=row["uid"],
            title=row["title"],
            summary=row["summary"],
            organism=row["organism"],
            platform=row["platform"],
            series_type=row["series_type"],
            sample_count=row["sample_count"],
            overall_design=row["overall_design"],
            ftp_link=row["ftp_link"],
            relations=relations,
        ))

    db.close()
    return datasets, run_id


if __name__ == "__main__":
    # Try loading from DB first, fallback to SOFT files
    datasets: list[GEODataset] = []
    run_id = 0
    source = ""
    loaded_from_db = False

    if DB_PATH.exists():
        datasets, run_id = load_datasets_from_db(DB_PATH)
        if datasets:
            source = f"database ({DB_PATH}, run_id={run_id})"
            loaded_from_db = True

    if not datasets:
        if not SOFT_DIR.exists():
            print(f"ERROR: neither DB '{DB_PATH}' nor SOFT_DIR '{SOFT_DIR}' found.")
            print("Run the GEO search test first:")
            print("  uv run python tests/01_Test_geo_search/run_geo_search.py")
            sys.exit(1)
        datasets = load_datasets_from_soft_dir(SOFT_DIR)
        source = f"SOFT files ({SOFT_DIR})"

    if not datasets:
        print("ERROR: no series data found.")
        sys.exit(1)

    print("=" * 70)
    print(f"Loaded {len(datasets)} series from {source}")
    with_relations = sum(1 for ds in datasets if ds.relations)
    print(f"  with relations : {with_relations}")
    print(f"  without        : {len(datasets) - with_relations}")
    print("=" * 70)

    # ── Open DB for persistence ───────────────────────────────────────────
    from geo_agent.db import Database as DB, DatabaseRepository as DBRepo

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db_inst = DB(DB_PATH)
    db_inst.open()
    repo = DBRepo(db_inst)

    # Use existing run_id if loaded from DB, otherwise create a new one
    if not run_id:
        run_id = repo.create_run(SearchQuery(data_type="(local)"))

    # When loaded from SOFT files, series rows don't exist in DB yet.
    # Insert them now so that HierarchySkill's UPDATE can find them.
    if not loaded_from_db:
        print(f"\n[db] Inserting {len(datasets)} series into DB (run_id={run_id})...")
        repo.save_series_batch(datasets, run_id)
        print(f"[db] Inserted {len(datasets)} series + their relations")

    ctx = PipelineContext(
        query=SearchQuery(data_type="(local)"),
        db=repo,
        pipeline_run_id=run_id,
    )
    ctx.datasets = datasets

    ctx = HierarchySkill(
        families_file=FAMILIES_FILE,
        standalone_file=STANDALONE_FILE,
    ).execute(ctx)

    h = ctx.series_hierarchy
    standalone_accs = [
        acc for acc, node in h.items()
        if node.role == "standalone" and node.in_search_results
    ]
    super_accs = [
        acc for acc, node in h.items()
        if node.role == "super" and node.in_search_results
    ]
    sub_accs = [
        acc for acc, node in h.items()
        if node.role == "sub" and node.in_search_results
    ]
    external_accs = [acc for acc, node in h.items() if not node.in_search_results]

    # ── Hierarchy tree ─────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("Hierarchy tree")
    print("=" * 70)
    print(format_series_hierarchy(h))

    # ── Role breakdown ─────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("Role breakdown (in search results)")
    print("=" * 70)
    print(f"  standalone : {len(standalone_accs)}")
    print(f"  super      : {len(super_accs)}")
    print(f"  sub        : {len(sub_accs)}")
    print(f"  external   : {len(external_accs)}  (referenced but not in results)")

    # ── What FetchFamilySoftSkill would process ────────────────────────────
    print("\n" + "=" * 70)
    print(f"Would pass to FetchFamilySoftSkill ({len(standalone_accs)} series)")
    print("=" * 70)
    for acc in sorted(standalone_accs):
        node = h[acc]
        title = f" -- {node.title}" if node.title else ""
        print(f"  {acc}{title}")

    if super_accs or sub_accs:
        print(f"\nSkipped (super/sub — not yet supported): {len(super_accs + sub_accs)}")
        for acc in sorted(super_accs + sub_accs):
            node = h[acc]
            print(f"  [{node.role}] {acc} -- {node.title}")

    if ctx.errors:
        print(f"\nErrors ({len(ctx.errors)}):")
        for e in ctx.errors:
            print(f"  - {e}")

    # ── Database verification ─────────────────────────────────────────────
    hierarchy_counts = db_inst.conn.execute(
        """SELECT hierarchy_role, COUNT(*) FROM series
           WHERE pipeline_run_id = ? AND hierarchy_role IS NOT NULL
           GROUP BY hierarchy_role""",
        (run_id,),
    ).fetchall()

    total_with_role = sum(row[1] for row in hierarchy_counts)
    total_null_role = db_inst.conn.execute(
        """SELECT COUNT(*) FROM series
           WHERE pipeline_run_id = ? AND hierarchy_role IS NULL""",
        (run_id,),
    ).fetchone()[0]

    print(f"\n{'=' * 70}")
    print(f"Database verification (run_id={run_id})")
    print(f"{'=' * 70}")
    print(f"  series in hierarchy (in-memory) : {len(h)}")
    print(f"  series with role (DB)           : {total_with_role}")
    if total_null_role:
        print(f"  series with NULL role (DB)      : {total_null_role}  *** NOT UPDATED ***")
    for row in hierarchy_counts:
        print(f"    {row[0]}: {row[1]}")

    # Verify: every in-memory hierarchy node should have a matching DB row
    if total_with_role == len(h):
        print(f"\n[ok] All {len(h)} series hierarchy roles persisted to DB")
    else:
        print(f"\n[WARN] Mismatch: {len(h)} nodes in-memory vs {total_with_role} updated in DB")

    # Show a few example rows for spot-checking
    sample_rows = db_inst.conn.execute(
        """SELECT accession, hierarchy_role, parent_accession, in_search_results
           FROM series WHERE pipeline_run_id = ?
           ORDER BY accession LIMIT 5""",
        (run_id,),
    ).fetchall()
    if sample_rows:
        print(f"\n  Sample DB rows:")
        print(f"  {'accession':<14} {'role':<12} {'parent':<14} {'in_results'}")
        print(f"  {'-'*14} {'-'*12} {'-'*14} {'-'*10}")
        for row in sample_rows:
            r = dict(row)
            print(f"  {r['accession']:<14} {r['hierarchy_role'] or 'NULL':<12} "
                  f"{r['parent_accession'] or '—':<14} {r['in_search_results']}")

    db_inst.close()
    print(f"\n[ok] Database saved to {DB_PATH}")
