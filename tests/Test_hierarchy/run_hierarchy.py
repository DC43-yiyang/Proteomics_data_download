"""HierarchySkill test — reads from local Series SOFT files.

Loads previously saved Series SOFT files from SOFT_DIR (populated by
run_geo_search.py or GEOSearchSkill with debug_dir set), reconstructs
GEODataset objects from them, and runs HierarchySkill.

No NCBI requests are made. Run the GEO search test first to populate SOFT_DIR:
    uv run python tests/Test_geo_search/run_geo_search.py

Usage
-----
    uv run python tests/Test_hierarchy/run_hierarchy.py

Environment overrides (all optional):
    SOFT_DIR        directory containing *.soft files (default: debug_soft/)
    FAMILIES_FILE   path to save family tree text (default: not saved)
    STANDALONE_FILE path to save standalone list text (default: not saved)
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

SOFT_DIR        = Path(os.getenv("SOFT_DIR",        "tests/Test_geo_search/debug_soft"))
FAMILIES_FILE   = os.getenv("FAMILIES_FILE",   "tests/Test_hierarchy/hierarchy_families.json") or None
STANDALONE_FILE = os.getenv("STANDALONE_FILE", "tests/Test_hierarchy/hierarchy_standalone.json") or None


def load_datasets_from_soft_dir(soft_dir: Path) -> list[GEODataset]:
    """Reconstruct GEODataset objects from saved Series SOFT files.

    Extracts accession, title, relations, and sample_count from each file.
    Fields not present in Series SOFT (organism, platform) are left empty.
    """
    soft_files = sorted(soft_dir.glob("*.soft"))
    if not soft_files:
        return []

    datasets: list[GEODataset] = []
    for path in soft_files:
        text = path.read_text(encoding="utf-8")
        parsed = parse_soft_text(text)

        accession = parsed.get("accession") or path.stem  # fallback: filename without .soft
        title = parsed.get("title", "")

        # relations: stored as "; "-joined string, split back to list
        relations_raw = parsed.get("relations", "")
        relations = [r.strip() for r in relations_raw.split("; ") if r.strip()]

        # sample_count: count !Series_sample_id entries
        sample_ids_raw = parsed.get("sample_ids", "")
        sample_count = len([s for s in sample_ids_raw.split("; ") if s.strip()])

        datasets.append(GEODataset(
            accession=accession,
            uid=accession,  # no real UID from local files; use accession as placeholder
            title=title,
            relations=relations,
            sample_count=sample_count,
        ))

    return datasets


if __name__ == "__main__":
    if not SOFT_DIR.exists():
        print(f"ERROR: SOFT_DIR '{SOFT_DIR}' not found.")
        print("Run the GEO search test first to populate it:")
        print("  uv run python tests/Test_geo_search/run_geo_search.py")
        sys.exit(1)

    datasets = load_datasets_from_soft_dir(SOFT_DIR)
    if not datasets:
        print(f"ERROR: no *.soft files found in '{SOFT_DIR}'.")
        sys.exit(1)

    print("=" * 70)
    print(f"Loaded {len(datasets)} Series SOFT files from '{SOFT_DIR}'")
    with_relations = sum(1 for ds in datasets if ds.relations)
    print(f"  with relations : {with_relations}")
    print(f"  without        : {len(datasets) - with_relations}")
    print("=" * 70)

    # HierarchySkill needs a minimal SearchQuery to construct PipelineContext
    ctx = PipelineContext(query=SearchQuery(data_type="(local)"))
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
