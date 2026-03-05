"""FetchFamilySoftSkill test — reads standalone series from hierarchy JSON.

Loads the standalone series list produced by run_hierarchy.py, reconstructs
a minimal series_hierarchy in context, and calls FetchFamilySoftSkill to
fetch Family SOFT files (targ=gsm) from NCBI.

No GEO search or hierarchy rebuild is performed. Run the hierarchy test first:
    uv run python tests/Test_hierarchy/run_hierarchy.py

Usage
-----
    uv run python tests/Test_fetch_family_soft/run_fetch_family_soft.py

Environment overrides (all optional):
    STANDALONE_JSON   path to hierarchy_standalone.json (default: tests/Test_hierarchy/hierarchy_standalone.json)
    SOFT_DIR          directory to save fetched Family SOFT files (default: tests/Test_fetch_family_soft/debug_family_soft)
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
    "tests/Test_hierarchy/hierarchy_standalone.json",
))
SOFT_DIR = Path(os.getenv("SOFT_DIR", "tests/Test_fetch_family_soft/debug_family_soft"))


def load_hierarchy_from_standalone_json(path: Path) -> dict[str, SeriesNode]:
    """Reconstruct a minimal series_hierarchy from a standalone JSON file.

    All series are assigned role='standalone' and in_search_results=True,
    which is exactly the filter FetchFamilySoftSkill applies.
    """
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


if __name__ == "__main__":
    if not STANDALONE_JSON.exists():
        print(f"ERROR: standalone JSON not found at '{STANDALONE_JSON}'.")
        print("Run the hierarchy test first:")
        print("  uv run python tests/Test_hierarchy/run_hierarchy.py")
        sys.exit(1)

    hierarchy = load_hierarchy_from_standalone_json(STANDALONE_JSON)
    if not hierarchy:
        print(f"ERROR: no series found in '{STANDALONE_JSON}'.")
        sys.exit(1)

    print("=" * 70)
    print(f"Loaded {len(hierarchy)} standalone series from '{STANDALONE_JSON}'")
    for acc, node in sorted(hierarchy.items()):
        title = f" -- {node.title}" if node.title else ""
        print(f"  {acc}{title}")
    print(f"\nFetching Family SOFT → {SOFT_DIR}/")
    print("=" * 70)

    config = load_config()
    client = NCBIClient(api_key=config.api_key, email=config.email, tool=config.tool_name)

    ctx = PipelineContext(query=SearchQuery(data_type="(local)"))
    ctx.series_hierarchy = hierarchy

    ctx = FetchFamilySoftSkill(client, soft_dir=SOFT_DIR).execute(ctx)

    print("\n" + "=" * 70)
    print(f"Fetched ({len(ctx.target_series_ids)}): {ctx.target_series_ids}")
    if ctx.errors:
        print(f"\nErrors ({len(ctx.errors)}):")
        for e in ctx.errors:
            print(f"  - {e}")
