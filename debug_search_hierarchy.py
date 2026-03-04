"""
GEO Agent — Search & Hierarchy debug script
============================================
Runs: Search → Hierarchy → (optional) Family SOFT fetch

Usage:
    .venv/bin/python debug_search_hierarchy.py
"""

import os

from geo_agent.agent import Agent
from geo_agent.config import load_config
from geo_agent.models.context import PipelineContext
from geo_agent.models.query import SearchQuery
from geo_agent.ncbi.client import NCBIClient
from geo_agent.ncbi.parsers import parse_family_soft
from geo_agent.skills.search import GEOSearchSkill
from geo_agent.skills.hierarchy import HierarchySkill
from geo_agent.utils.hierarchy import format_series_hierarchy
from geo_agent.utils.logging import setup_logging

# ============================================================
# Query parameters
# ============================================================

QUERY = SearchQuery(
    data_type="CITE-seq",
    organism="Homo sapiens",
    disease=None,
    tissue=None,
    max_results=30,
)

# ============================================================
# Output paths (set to None to skip saving)
# ============================================================

SOFT_DEBUG_DIR = "debug_soft/"                      # Raw Series SOFT files
FAMILIES_FILE = "debug_hierarchy_families.txt"      # Family tree output
STANDALONE_FILE = "debug_hierarchy_standalone.txt"  # Standalone list output

# ============================================================
# Family SOFT fetch
# ============================================================

FETCH_FAMILY_SOFT = True                           # Fetch Family SOFT for standalone series
FAMILY_SOFT_DEBUG_DIR = "debug_family_soft/"        # Save raw Family SOFT files here

# ============================================================
# No need to edit below
# ============================================================

if __name__ == "__main__":
    setup_logging(verbose=True)

    config = load_config()
    client = NCBIClient(api_key=config.api_key, email=config.email, tool=config.tool_name)

    agent = Agent()
    agent.register(GEOSearchSkill(client, debug_dir=SOFT_DEBUG_DIR))
    agent.register(HierarchySkill(
        ncbi_client=client,
        families_file=FAMILIES_FILE,
        standalone_file=STANDALONE_FILE,
    ))

    ctx = PipelineContext(query=QUERY)
    ctx = agent.run(ctx)

    # Print hierarchy
    if ctx.series_hierarchy:
        print("\n" + "=" * 70)
        print("Series hierarchy")
        print("=" * 70)
        print(format_series_hierarchy(ctx.series_hierarchy))

    # Fetch Family SOFT for standalone series
    if FETCH_FAMILY_SOFT and ctx.series_hierarchy:
        standalone_accs = [
            acc for acc, node in ctx.series_hierarchy.items()
            if node.role == "standalone" and node.in_search_results
        ]

        print("\n" + "=" * 70)
        print(f"Fetching Family SOFT for {len(standalone_accs)} standalone series")
        print("=" * 70)

        if FAMILY_SOFT_DEBUG_DIR:
            os.makedirs(FAMILY_SOFT_DEBUG_DIR, exist_ok=True)

        soft_texts = client.fetch_family_soft_batch(standalone_accs)

        for acc, soft_text in soft_texts.items():
            if not soft_text:
                print(f"\n  {acc}: FAILED to fetch (empty response)")
                continue

            if FAMILY_SOFT_DEBUG_DIR:
                out_path = os.path.join(FAMILY_SOFT_DEBUG_DIR, f"{acc}_family.soft")
                with open(out_path, "w") as f:
                    f.write(soft_text)
                print(f"\n  {acc}: saved to {out_path} ({len(soft_text)} chars)")

            samples = parse_family_soft(soft_text)
            print(f"  {acc}: {len(samples)} samples parsed")

    if ctx.errors:
        print(f"\nErrors ({len(ctx.errors)}):")
        for e in ctx.errors:
            print(f"  - {e}")
