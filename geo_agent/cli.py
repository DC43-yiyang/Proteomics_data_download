import sys

from geo_agent.utils.logging import setup_logging


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="geo-agent",
        description="Search and analyze GEO datasets",
    )
    sub = parser.add_subparsers(dest="command")

    # search subcommand
    search_p = sub.add_parser("search", help="Search GEO for datasets")
    search_p.add_argument(
        "--data-type", required=True,
        help='Data type to search for (e.g. "CITE-seq", "scRNA-seq", "WGS")',
    )
    search_p.add_argument(
        "--organism", default=None,
        help='Organism filter (e.g. "Homo sapiens")',
    )
    search_p.add_argument(
        "--disease", default=None,
        help='Disease filter (e.g. "breast cancer")',
    )
    search_p.add_argument(
        "--tissue", default=None,
        help='Tissue/cell type filter (e.g. "PBMC", "T cells")',
    )
    search_p.add_argument(
        "--max-results", type=int, default=100,
        help="Maximum number of results to return (default: 100)",
    )
    search_p.add_argument(
        "--report", default=None,
        help="Save report to a Markdown file (e.g. --report results.md)",
    )
    search_p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show detailed info for each dataset",
    )
    search_p.add_argument(
        "--library-type", action="append", default=None,
        help=(
            "Filter samples by library type (e.g. GEX, ADT, TCR, BCR, HTO, ATAC). "
            "Repeatable: --library-type GEX --library-type ADT. "
            "Uses local Family SOFT parsing (rule-based)."
        ),
    )
    search_p.add_argument(
        "--family-soft-dir", default="debug_family_soft",
        help=(
            "Directory containing local *_family.soft files for sample-level parsing "
            "(default: debug_family_soft)."
        ),
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    setup_logging(verbose=getattr(args, "verbose", False))

    if args.command == "search":
        _run_search(args)


def _run_search(args):
    from geo_agent.agent import Agent
    from geo_agent.config import load_config
    from geo_agent.models.context import PipelineContext
    from geo_agent.models.query import SearchQuery
    from geo_agent.ncbi.client import NCBIClient
    from geo_agent.skills.search import GEOSearchSkill
    from geo_agent.skills.report import ReportSkill

    config = load_config()
    client = NCBIClient(
        api_key=config.api_key,
        email=config.email,
        tool=config.tool_name,
    )

    query = SearchQuery(
        data_type=args.data_type,
        organism=args.organism,
        disease=args.disease,
        tissue=args.tissue,
        max_results=args.max_results,
    )

    # Database setup (optional)
    db = None
    repo = None
    run_id = None
    if config.db_path:
        from geo_agent.db import Database, DatabaseRepository
        db = Database(config.db_path)
        db.open()
        repo = DatabaseRepository(db)
        run_id = repo.create_run(query)

    agent = Agent()
    agent.register(GEOSearchSkill(client))
    agent.register(ReportSkill(output_file=args.report))

    # When --library-type is provided, add HierarchySkill + FilterSkill + FamilySoftStructurerSkill
    library_types = getattr(args, "library_type", None)
    if library_types:
        from geo_agent.skills.filter import FilterSkill

        from geo_agent.skills.hierarchy import HierarchySkill
        from geo_agent.skills.family_soft_structurer import FamilySoftStructurerSkill

        agent.register(HierarchySkill(ncbi_client=client))
        agent.register(FilterSkill())
        agent.register(FamilySoftStructurerSkill(soft_dir=args.family_soft_dir))

    context = PipelineContext(query=query, db=repo, pipeline_run_id=run_id)
    if library_types:
        context.target_library_types = [t.upper() for t in library_types]

    try:
        context = agent.run(context)
    finally:
        if repo and run_id is not None:
            status = "failed" if context.errors else "completed"
            repo.finish_run(run_id, context.total_found, status)
        if db:
            db.close()

    # Print the Markdown report to stdout
    print(context.report or "No report generated.")

    # Print sample-level structuring summary if --library-type was used.
    if library_types and context.family_soft_structured:
        target_types = {item.upper() for item in library_types}
        print("\n\n## Family SOFT Parsing Summary\n")
        for gse, series in sorted(context.family_soft_structured.items()):
            samples = series.get("samples", [])
            matched = [
                item
                for item in samples
                if str(item.get("inferred_library_type", "")).upper() in target_types
            ]
            print(f"\n### {gse} ({len(matched)} matched / {len(samples)} total)\n")
            print("| GSM | Modality | Tissue | Cell Type | Files | SRA | Notes |")
            print("|-----|----------|--------|-----------|-------|-----|-------|")
            for item in matched:
                core = item.get("core_characteristics", {}) or {}
                notes = "; ".join(item.get("notes", []) or [])
                print(
                    f"| {item.get('gsm_id', '')} | {item.get('inferred_library_type', '')} "
                    f"| {core.get('tissue', '')} | {core.get('cell type', '')} "
                    f"| {len(item.get('supplementary_files', []) or [])} "
                    f"| {len(item.get('relation_sra', []) or [])} | {notes} |"
                )

            watchlist = series.get("keyword_watchlist", []) or []
            if watchlist:
                top = ", ".join(
                    f"{entry.get('keyword', '')}({entry.get('count', 0)})"
                    for entry in watchlist[:10]
                )
                print(f"\nUnmapped keywords (top): {top}\n")

    if library_types and context.errors:
        print("\n\n## Sample Parsing Errors\n")
        for err in context.errors:
            if "Family SOFT file not found" in err or "failed to structure Family SOFT" in err:
                print(f"- {err}")


if __name__ == "__main__":
    main()
