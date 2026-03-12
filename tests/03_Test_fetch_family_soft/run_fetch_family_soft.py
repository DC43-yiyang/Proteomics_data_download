"""FetchFamilySoftSkill test — reads standalone series from hierarchy JSON or database.

Loads the standalone series list from DB (preferred) or from the JSON file
produced by run_hierarchy.py, reconstructs a minimal series_hierarchy in
context, and calls FetchFamilySoftSkill to fetch Family SOFT files from NCBI.

No GEO search or hierarchy rebuild is performed. Run the hierarchy test first:
    uv run python tests/02_Test_hierarchy/run_hierarchy.py

Usage
-----
    uv run python tests/03_Test_fetch_family_soft/run_fetch_family_soft.py

Environment overrides (all optional):
    STANDALONE_JSON   path to hierarchy_standalone.json (default: tests/02_Test_hierarchy/hierarchy_standalone.json)
    SOFT_DIR          directory to save fetched Family SOFT files (default: tests/03_Test_fetch_family_soft/debug_family_soft)
    DB_PATH           SQLite database path (default: data/geo_agent.db)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from geo_agent.config import load_config
from geo_agent.models.context import PipelineContext
from geo_agent.models.query import SearchQuery
from geo_agent.ncbi.client import NCBIClient
from geo_agent.skills.fetch_family_soft import FetchFamilySoftSkill
from geo_agent.utils.hierarchy import SeriesNode
from geo_agent.utils.logging import setup_logging

setup_logging(verbose=True)
logger = logging.getLogger(__name__)

STANDALONE_JSON = Path(os.getenv(
    "STANDALONE_JSON",
    "tests/02_Test_hierarchy/hierarchy_standalone.json",
))
SOFT_DIR = Path(os.getenv("SOFT_DIR", "tests/03_Test_fetch_family_soft/debug_family_soft"))
DB_PATH  = Path(os.getenv("DB_PATH", "data/geo_agent.db"))


def load_hierarchy_from_standalone_json(path: Path) -> dict[str, SeriesNode]:
    """Reconstruct a minimal series_hierarchy from a standalone JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    hierarchy: dict[str, SeriesNode] = {}
    for entry in data.get("series", []):
        acc = entry["accession"]
        hierarchy[acc] = SeriesNode(
            accession=acc,
            title=entry.get("title", ""),
            role="standalone",
            in_search_results=True,
        )
    return hierarchy


def load_hierarchy_from_db(db_path: Path) -> dict[str, SeriesNode]:
    """Load standalone series from the database (latest pipeline run)."""
    from geo_agent.db import Database, DatabaseRepository

    db = Database(db_path)
    db.open()
    repo = DatabaseRepository(db)

    run_id = repo.get_latest_run_id()
    if run_id is None:
        db.close()
        return {}

    rows = db.conn.execute(
        """SELECT accession, title, hierarchy_role, parent_accession, in_search_results
           FROM series
           WHERE pipeline_run_id = ? AND hierarchy_role = 'standalone'
           AND in_search_results = 1""",
        (run_id,),
    ).fetchall()

    hierarchy: dict[str, SeriesNode] = {}
    for row in rows:
        r = dict(row)
        hierarchy[r["accession"]] = SeriesNode(
            accession=r["accession"],
            title=r["title"],
            role="standalone",
            in_search_results=True,
        )

    db.close()
    return hierarchy


if __name__ == "__main__":
    # Try loading from DB first, fallback to JSON
    hierarchy: dict[str, SeriesNode] = {}
    source = ""

    if DB_PATH.exists():
        hierarchy = load_hierarchy_from_db(DB_PATH)
        if hierarchy:
            source = f"database ({DB_PATH})"

    if not hierarchy:
        if not STANDALONE_JSON.exists():
            print(f"ERROR: neither DB '{DB_PATH}' nor standalone JSON '{STANDALONE_JSON}' found.")
            print("Run the hierarchy test first:")
            print("  uv run python tests/02_Test_hierarchy/run_hierarchy.py")
            sys.exit(1)
        hierarchy = load_hierarchy_from_standalone_json(STANDALONE_JSON)
        source = f"JSON ({STANDALONE_JSON})"

    if not hierarchy:
        print(f"ERROR: no standalone series found.")
        sys.exit(1)

    print("=" * 70)
    print(f"Loaded {len(hierarchy)} standalone series from {source}")
    for acc, node in sorted(hierarchy.items()):
        title = f" -- {node.title}" if node.title else ""
        print(f"  {acc}{title}")
    print(f"\nFetching Family SOFT → {SOFT_DIR}/")
    print("=" * 70)

    config = load_config()
    client = NCBIClient(api_key=config.api_key, email=config.email, tool=config.tool_name)

    # No DB persistence for this step (files saved to disk only)
    ctx = PipelineContext(query=SearchQuery(data_type="(local)"))
    ctx.series_hierarchy = hierarchy

    ctx = FetchFamilySoftSkill(client, soft_dir=SOFT_DIR).execute(ctx)

    print("\n" + "=" * 70)
    print(f"Fetched ({len(ctx.target_series_ids)}): {ctx.target_series_ids}")
    if ctx.errors:
        print(f"\nErrors ({len(ctx.errors)}):")
        for e in ctx.errors:
            print(f"  - {e}")
